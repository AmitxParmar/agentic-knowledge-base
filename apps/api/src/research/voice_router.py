"""
research/voice_router.py
------------------------
Purpose:    Bidirectional real-time voice endpoint for the research agent.
            One WebSocket = continuous voice session (unlike /ws where one
            connection = one run).
Protocol:
  Client → server  binary:  raw float32 PCM, 16 kHz mono (mic frames)
  Client → server  text:    {"action": "start"} | {"action": "stop"}
  Server → client  binary:  MP3 audio chunks for playback (TTS)
  Server → client  text:    {"type": "ready"} | {"type": "transcript", "text"}
                            {"type": "answer", "run_id", "text", "citations"}
                            {"type": "latency", "stages"} | {"type": "done"}
                            {"type": "error", "message"}
Design notes:
- VAD endpointing decides the utterance boundary; the LLM + TTS pipeline runs
  as a task. When interrupt is on (VOICE_INTERRUPTIBLE), a new utterance
  cancels the previous task — the user can talk over playback.
- Only the fixed ux.md progress vocabulary and the final transcript/answer
  cross to the client; never chain-of-thought or raw model output.
Dependencies: voice_stt, voice_tts, research/agent, shared/*, auth/stub
Scope:      Transport + orchestration only.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time as _time
import uuid
from datetime import UTC, datetime
from typing import Any

import logfire
import numpy as np
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import settings
from src.auth.stub import get_user_id, get_workspace_id
from src.research.agent import run_agent
from src.research.models import ResearchRun, RunStatus
from src.research.voice_stt import VoiceActivityDetector, transcribe_utterance
from src.research.voice_tts import tts_chunks
from src.shared.database import get_session
from src.shared.progress import ResearchStage

router = APIRouter()
logger = logging.getLogger(__name__)


def _ws_client_ip(ws: WebSocket) -> str:
    return ws.client.host if ws.client else "unknown"


async def _check_voice_rate_limit(ws: WebSocket) -> bool:
    """Returns True if allowed. Uses the shared Redis fixed-window limiter."""
    from src.shared.rate_limit import _check_limit

    return await _check_limit("voice", _ws_client_ip(ws), settings.VOICE_RATE_LIMIT)


class _Pipeline:
    """One user turn: STT → agent → TTS, cancellable as a task."""

    def __init__(
        self, ws: WebSocket, session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        self._ws = ws
        self._session = session
        self._workspace_id = workspace_id
        self._user_id = user_id
        self._stages_ms: dict[str, int] = {}

    async def run(self, utterance: Any) -> None:
        try:
            await self._send("transcript", text="(listening…)")

            t0 = _time.monotonic()
            text = await transcribe_utterance(utterance)
            self._stages_ms["stt"] = round((_time.monotonic() - t0) * 1000)
            if not text:
                await self._send("transcript", text="(no speech detected)")
                return
            await self._send("transcript", text=text)

            t1 = _time.monotonic()
            answers = await self._run_agent(text)
            self._stages_ms["agent"] = round((_time.monotonic() - t1) * 1000)

            t2 = _time.monotonic()
            answer, citations = answers
            await self._send(
                "answer",
                run_id=str(self._run_id),
                text=answer,
                citations=citations,
            )

            # Stream TTS; give up (text-only fallback) on synthesis errors.
            try:
                async for chunk in tts_chunks(answer):
                    await self._ws.send_bytes(chunk)
            except Exception:
                logger.warning("voice_router: TTS failed, sending text-only")
            self._stages_ms["tts"] = round((_time.monotonic() - t2) * 1000)

            await self._send("latency", stages=self._stages_ms)
            await self._send("done")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("voice_router: pipeline failed")
            await self._send(
                "error", message="An error occurred while processing your voice request."
            )

    async def _run_agent(self, question: str):
        run = ResearchRun(
            workspace_id=self._workspace_id,
            user_id=self._user_id,
            question=question,
            status=RunStatus.running,
        )
        self._session.add(run)
        await self._session.flush()
        self._run_id = run.id

        async def on_stage(stage: ResearchStage) -> None:
            await self._send("stage", stage=stage.value)

        with logfire.span("voice.run", run_id=str(run.id), question=question[:80]):
            result = await run_agent(
                question=question,
                workspace_id=self._workspace_id,
                run_id=run.id,
                session=self._session,
                stage_callback=on_stage,
            )

            run.answer = result.answer
            run.iteration_count = result.iterations
            run.token_count = result.tokens_used
            run.status = RunStatus.complete
            run.completed_at = datetime.now(UTC)
            await self._session.commit()

        citations = [
            {
                "chunk_id": c["chunk_id"],
                "source_ref": c["source_ref"],
                "relevance_score": round(c.get("relevance_score", 0.0), 4),
            }
            for c in result.citations
        ]
        return result.answer, citations

    async def _send(self, type_: str, **payload: Any) -> None:
        await self._ws.send_text(json.dumps({"type": type_, **payload}))


@router.websocket("/ws/voice")
async def voice_websocket(
    ws: WebSocket,
    session: AsyncSession = Depends(get_session),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user_id: uuid.UUID = Depends(get_user_id),
) -> None:
    """Bidirectional voice research session. Binary PCM in, MP3 + JSON out."""
    if not await _check_voice_rate_limit(ws):
        await ws.accept()
        await ws.send_text(
            json.dumps({"type": "error", "message": "Too many voice requests. Please slow down."})
        )
        await ws.close()
        return

    await ws.accept()
    await ws.send_text(json.dumps({"type": "ready"}))

    detector = VoiceActivityDetector()
    pipeline = _Pipeline(ws, session, workspace_id, user_id)
    current: asyncio.Task[Any] | None = None

    async def start_turn(utterance: Any) -> None:
        nonlocal current
        if settings.VOICE_INTERRUPTIBLE and current is not None and not current.done():
            current.cancel()
        current = asyncio.create_task(pipeline.run(utterance))

    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break

            data = message.get("bytes")
            if data is not None:
                chunk = np.frombuffer(data, dtype=np.float32)
                utterance = detector.push(chunk)
                if utterance is not None:
                    await start_turn(utterance)
                continue

            text = message.get("text")
            if text:
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                action = payload.get("action")
                if action == "stop":
                    utterance = detector.flush()
                    if utterance is not None:
                        await start_turn(utterance)
                    elif current is not None and not current.done():
                        current.cancel()

    except WebSocketDisconnect:
        logger.info("voice_router: client disconnected")
    finally:
        if current is not None and not current.done():
            current.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await current
