"""
research/router.py
------------------
Purpose:    WebSocket endpoint for research runs.
            Client connects → sends question → receives progress stages → receives answer.
Dependencies: research/agent, research/models, shared/progress, shared/database, auth/stub
Scope:      Transport only. Agent logic lives in research/agent.py.

Protocol:
  Client → server: {"question": "...", "workspace_id": "..."}   (on connect)
  Server → client: {"type": "progress", "stage": "Searching documents..."}  (repeated)
  Server → client: {"type": "answer", "text": "...", "citations": [...]}
  Server → client: {"type": "error", "message": "..."}  (on failure)

ux.md rule: never send chain-of-thought, tool payloads, or raw model output
over this channel. Only the fixed stage vocabulary and the final answer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import logfire
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.stub import get_user_id, get_workspace_id
from src.research.agent import run_agent
from src.research.models import ResearchRun, RunStatus
from src.research.usage import BudgetExceededError, get_budget_status, workspace_today_tokens
from src.retrieval.pipeline import RetrievalError
from src.shared.database import get_session
from src.shared.model_gateway import ProviderError, RateLimitError
from src.shared.progress import ResearchStage, emit, emit_done, emit_error
from src.shared.prompt_safety import MAX_QUESTION_CHARS, sanitize_user_text
from src.shared.rate_limit import check_chat_rate_limit
from src.shared.semantic_cache import SemanticCache

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Error codes (structured, user-facing) ────────────────────────────────────

ERROR_CODES: dict[str, str] = {
    "RATE_LIMIT": "The model provider is rate limited. Please wait a moment and try again.",
    "PROVIDER_ERROR": "The model provider is unavailable. Please check provider status and try again.",
    "RETRIEVAL_ERROR": "An error occurred while searching the documents. Please try again.",
    "TOOL_PARSE_ERROR": "The model produced a malformed tool call. Please try again.",
    "BUDGET_EXCEEDED": "Daily token budget exhausted. Please try again tomorrow.",
    "AGENT_ERROR": "An error occurred during the research run.",
}


def _error_code(exc: Exception) -> str:
    if isinstance(exc, RateLimitError):
        return "RATE_LIMIT"
    if isinstance(exc, ProviderError):
        return "PROVIDER_ERROR"
    if isinstance(exc, RetrievalError):
        return "RETRIEVAL_ERROR"
    if isinstance(exc, BudgetExceededError):
        return "BUDGET_EXCEEDED"
    if isinstance(exc, json.JSONDecodeError):
        return "TOOL_PARSE_ERROR"
    return "AGENT_ERROR"


def _citation_payload(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize agent citations to the wire format (ux.md citation display)."""
    return [
        {
            "chunk_id": c["chunk_id"],
            "source_ref": c["source_ref"],
            "relevance_score": round(c.get("relevance_score", 0.0), 4),
        }
        for c in citations
    ]


@router.websocket("/ws")
async def research_websocket(
    ws: WebSocket,
    session: AsyncSession = Depends(get_session),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user_id: uuid.UUID = Depends(get_user_id),
) -> None:
    """
    WebSocket research endpoint. One connection = one research run.

    Expected first message from client:
      {"question": "What does the uploaded PDF say about X?"}
    """
    await ws.accept()

    run: ResearchRun | None = None
    try:
        # Receive question from client
        raw = await ws.receive_text()
        payload = json.loads(raw)
        question = payload.get("question", "").strip()

        if not question:
            await emit_error(ws, "Question cannot be empty.")
            await ws.close()
            return
        if len(question) > MAX_QUESTION_CHARS:
            await emit_error(ws, f"Question is too long (max {MAX_QUESTION_CHARS} characters).")
            await ws.close()
            return
        question = sanitize_user_text(question)

        # Semantic cache — return the cached answer on a similar-question hit,
        # skipping the full pipeline (ADR-007). Never raises; a Redis failure
        # degrades to a normal run.
        cache = SemanticCache()
        hit = await cache.lookup(str(workspace_id), question)
        if hit:
            run = ResearchRun(
                workspace_id=workspace_id,
                user_id=user_id,
                question=question,
                answer=hit.answer,
                status=RunStatus.complete,
                completed_at=datetime.now(UTC),
            )
            session.add(run)
            await session.commit()
            # Replay the fixed stage vocabulary so the UI behaves identically
            # to a live run (ux.md vocabulary only).
            for stage in ResearchStage:
                await emit(ws, stage)
            await ws.send_text(
                json.dumps(
                    {
                        "type": "answer",
                        "run_id": str(run.id),
                        "text": hit.answer,
                        "citations": _citation_payload(hit.citations),
                    }
                )
            )
            await emit_done(ws)
            await ws.close()
            return

        # Create ResearchRun row
        run = ResearchRun(
            workspace_id=workspace_id,
            user_id=user_id,
            question=question,
            status=RunStatus.running,
        )
        session.add(run)
        await session.flush()

        with logfire.span("research.run", run_id=str(run.id), question=question[:80]):
            # Progress callback — bridges agent → WebSocket (ux.md vocabulary only)
            async def on_stage(stage: ResearchStage) -> None:
                await emit(ws, stage)

            result = await run_agent(
                question=question,
                workspace_id=workspace_id,
                run_id=run.id,
                session=session,
                stage_callback=on_stage,
                user_id=str(user_id),
            )

            # Update run with final answer
            run.answer = result.answer
            run.iteration_count = result.iterations
            run.token_count = result.tokens_used
            run.status = RunStatus.complete
            run.completed_at = datetime.now(UTC)
            await session.commit()

            # Cache the completed answer — best-effort, never blocks the run
            await cache.store(
                str(workspace_id), question, result.answer, result.citations, result.confidence
            )

        # Send the final answer with citations
        # Citations include source_ref for the UI to display (ux.md citation display requirement)
        await ws.send_text(
            json.dumps(
                {
                    "type": "answer",
                    "run_id": str(run.id),
                    "text": result.answer,
                    "citations": _citation_payload(result.citations),
                }
            )
        )
        await emit_done(ws)

    except WebSocketDisconnect:
        logger.info("client disconnected mid-run")
        # Best-effort: mark run failed if it was created
        try:
            if run and run.id:
                run.status = RunStatus.failed
                await session.commit()
        except Exception:
            pass

    except Exception as exc:
        logger.exception("research run failed")
        logfire.error("research.run.failed", error=str(exc))
        # Step 1: typed user-safe message (budget, provider, retrieval...).
        # Step 2: never leak internals — fall back to the generic message.
        code = _error_code(exc)
        await emit_error(ws, ERROR_CODES[code])
        try:
            if run:
                run.status = RunStatus.failed
                await session.commit()
        except Exception:
            pass
        await ws.close()


# ── AG-UI SSE endpoint (Option B, ADR-005) ─────────────────────────────────


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question: str | None = Field(default=None, max_length=MAX_QUESTION_CHARS)
    messages: list[dict[str, Any]] | None = None
    thread_id: str | None = Field(default=None, alias="threadId")


# One lock per conversation so a thread can't start a second run while the
# first is still streaming (client guard + server lock = defense in depth).
# Keyed by (event-loop id, thread id): asyncio.Lock binds to the loop that
# first awaits it, and TestClient creates a fresh loop per request, so a lock
# cached across loops would raise "bound to a different event loop". Production
# runs a single loop per worker, where this serializes per thread as intended.
_conversation_locks: dict[tuple[int, str], asyncio.Lock] = {}
_locks_guard = threading.Lock()


def _get_conversation_lock(thread_id: str) -> asyncio.Lock:
    with _locks_guard:
        key = (id(asyncio.get_running_loop()), thread_id)
        lock = _conversation_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _conversation_locks[key] = lock
        return lock


async def agui_event_stream(
    question: str,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    session: AsyncSession,
    history: list[dict[str, Any]] | None = None,
    thread_id: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream AG-UI events for a research run. Bridges agent callbacks via queue."""
    run_id = uuid.uuid4()
    message_id = str(run_id)
    queue: asyncio.Queue = asyncio.Queue()

    yield {"type": "RUN_STARTED", "threadId": str(run_id), "runId": str(run_id)}
    yield {"type": "TEXT_MESSAGE_START", "messageId": message_id, "role": "assistant"}

    # Semantic cache — short-circuit on a similar-question hit (ADR-007).
    # ponytail: keyed on the question only; multi-turn context is ignored,
    # TTL (1h default) bounds the staleness window.
    cache = SemanticCache()
    hit = await cache.lookup(str(workspace_id), question)
    if hit:
        run = ResearchRun(
            workspace_id=workspace_id,
            user_id=user_id,
            question=question,
            answer=hit.answer,
            status=RunStatus.complete,
            completed_at=datetime.now(UTC),
        )
        session.add(run)
        await session.commit()
        for stage in ResearchStage:
            yield {"type": "CUSTOM", "name": "stage", "value": {"stage": stage.value}}
        yield {
            "type": "CUSTOM",
            "name": "citations",
            "value": {
                "run_id": str(run.id),
                "confidence": hit.confidence,
                "citations": _citation_payload(hit.citations),
            },
        }
        yield {"type": "TEXT_MESSAGE_CONTENT", "messageId": message_id, "delta": hit.answer}
        yield {"type": "TEXT_MESSAGE_END", "messageId": message_id}
        yield {"type": "RUN_FINISHED", "threadId": str(run_id), "runId": str(run_id)}
        return

    run = ResearchRun(
        workspace_id=workspace_id,
        user_id=user_id,
        question=question,
        status=RunStatus.running,
    )
    session.add(run)
    await session.flush()

    # Tracks streamed answer deltas: when synthesis produced none (empty
    # stream edge), the full answer is sent once below instead.
    deltas_seen = [0]

    async def on_stage(stage: ResearchStage | str) -> None:
        # Step 1: progress stages travel as AG-UI CUSTOM events (name/value),
        # not text deltas, so they render in the progress strip instead of
        # inside the answer bubble. NOTE: ResearchStage is a str enum, so it
        # must be matched before the plain-str branch below.
        if isinstance(stage, ResearchStage):
            await queue.put({"type": "CUSTOM", "name": "stage", "value": {"stage": stage.value}})
            return
        # Step 2: raw strings are synthesis text deltas — forward them as
        # AG-UI content events so the answer paints token-by-token.
        deltas_seen[0] += 1
        await queue.put({"type": "TEXT_MESSAGE_CONTENT", "messageId": message_id, "delta": stage})

    async def run_agent_task() -> Any:
        return await run_agent(
            question=question,
            workspace_id=workspace_id,
            run_id=run.id,
            session=session,
            stage_callback=on_stage,
            history=history,
            user_id=str(user_id),
            # Group multi-turn runs of one conversation into a Langfuse session
            session_id=thread_id or str(run.id),
        )

    try:
        with logfire.span("research.run", run_id=str(run_id), question=question[:80]):
            asyncio_task = asyncio.create_task(run_agent_task())

            while not asyncio_task.done():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.5)
                    yield event
                except TimeoutError:
                    continue

            while not queue.empty():
                yield queue.get_nowait()

            result = await asyncio_task
            run.answer = result.answer
            run.iteration_count = result.iterations
            run.token_count = result.tokens_used
            run.status = RunStatus.complete
            run.completed_at = datetime.now(UTC)
            await session.commit()

            # Cache the completed answer — best-effort, never blocks the run
            await cache.store(
                str(workspace_id), question, result.answer, result.citations, result.confidence
            )

        # Citations carry source_ref + relevance_score for the UI to resolve
        # the [n] markers in the answer (ux.md citation display requirement).
        # Confidence flags runs where evidence was thin so the UI can warn.
        yield {
            "type": "CUSTOM",
            "name": "citations",
            "value": {
                "run_id": str(run.id),
                "confidence": result.confidence,
                "citations": _citation_payload(result.citations),
            },
        }
        # The live path already streamed the answer delta-by-delta; send the
        # whole answer only when nothing was streamed (empty-stream edge).
        if deltas_seen[0] == 0 and result.answer:
            yield {"type": "TEXT_MESSAGE_CONTENT", "messageId": message_id, "delta": result.answer}
        yield {"type": "TEXT_MESSAGE_END", "messageId": message_id}
        yield {"type": "RUN_FINISHED", "threadId": str(run_id), "runId": str(run_id)}

    except Exception as exc:
        logger.exception("research run failed")
        logfire.error("research.run.failed", error=str(exc))
        try:
            run.status = RunStatus.failed
            await session.commit()
        except Exception:
            pass
        code = _error_code(exc)
        yield {"type": "RUN_ERROR", "message": ERROR_CODES[code], "code": code}


@router.post("/chat")
async def research_chat(
    request: ChatRequest,
    _rate: None = Depends(check_chat_rate_limit),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user_id: uuid.UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """AG-UI SSE endpoint for research runs. Streams typed events."""
    question = (request.question or "").strip()
    if not question and request.messages:
        for msg in reversed(request.messages):
            if msg.get("role") == "user":
                parts = msg.get("parts", [])
                for part in parts:
                    if part.get("type") == "text" and part.get("content"):
                        question = part["content"].strip()
                        break
                if not question:
                    question = msg.get("content", "").strip()
                if question:
                    break
    if not question:
        raise HTTPException(status_code=422, detail="Question cannot be empty.")
    if len(question) > MAX_QUESTION_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Question is too long (max {MAX_QUESTION_CHARS} characters).",
        )
    question = sanitize_user_text(question)

    thread_id = request.thread_id or "default"

    async def event_generator():
        lock = _get_conversation_lock(thread_id)
        async with lock:
            async for event in agui_event_stream(
                question,
                workspace_id,
                user_id,
                session,
                history=request.messages,
                thread_id=thread_id,
            ):
                yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/cache/stats")
async def cache_stats(
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> dict[str, int]:
    """Semantic-cache hit-rate counters for the workspace (ADR-007)."""
    return await SemanticCache().stats(str(workspace_id))


@router.get("/model-info")
async def model_info() -> dict[str, str]:
    """Exposed for UI header — which LLM is actually wired via the gateway.

    Frontend shows primary + fallback so users know why RATE_LIMIT points
    to Groq vs OpenRouter. No secrets leaked.
    """
    from app.settings import settings

    primary = f"{settings.MODEL_GATEWAY_PROVIDER}/{settings.MODEL_GATEWAY_MODEL}"
    fallback = f"openrouter/{settings.MODEL_GATEWAY_OPENROUTER_MODEL}"
    return {
        "provider": settings.MODEL_GATEWAY_PROVIDER,
        "model": settings.MODEL_GATEWAY_MODEL,
        "primary": primary,
        "fallback": fallback,
        "fallback_model": settings.MODEL_GATEWAY_OPENROUTER_MODEL,
    }


class RunSummary(BaseModel):
    run_id: str
    question: str
    status: str
    created_at: str
    token_count: int = 0


class RunListResponse(BaseModel):
    runs: list[RunSummary]
    total: int


@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> RunListResponse:
    """List research runs in the workspace, newest first, paginated."""
    count_result = await session.execute(
        select(func.count(ResearchRun.id)).where(ResearchRun.workspace_id == workspace_id)
    )
    total = count_result.scalar_one()

    result = await session.execute(
        select(ResearchRun)
        .where(ResearchRun.workspace_id == workspace_id)
        .order_by(ResearchRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    runs = result.scalars().all()

    return RunListResponse(
        runs=[
            RunSummary(
                run_id=str(run.id),
                question=run.question,
                status=run.status.value,
                created_at=run.created_at.isoformat(),
                token_count=run.token_count,
            )
            for run in runs
        ],
        total=total,
    )


@router.get("/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Fetch a completed research run with its citations."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    result = await session.execute(
        select(ResearchRun)
        .options(selectinload(ResearchRun.citations))
        .where(ResearchRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        from src.shared.errors import NotFoundError

        raise NotFoundError(f"Run {run_id} not found")

    return {
        "run_id": str(run.id),
        "question": run.question,
        "answer": run.answer,
        "status": run.status.value,
        "token_count": run.token_count,
        "citations": [{"chunk_id": str(c.chunk_id)} for c in run.citations],
        "created_at": run.created_at.isoformat(),
    }


@router.get("/usage")
async def usage_summary(
    user_id: uuid.UUID = Depends(get_user_id),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Per-user token spend vs the daily budget (powers the usage dashboard).

    Also reports the workspace-wide total — the soft cost ceiling for the
    workspace as a whole (hard daily limits are enforced per user).
    """
    # Step 1: aggregate spend in both windows + the effective budget.
    status = await get_budget_status(session, user_id)
    workspace_today = await workspace_today_tokens(session, workspace_id)
    # Step 2: shape the client payload (JSON-safe; budget may be null).
    return {
        "today_tokens": status.today_tokens,
        "month_tokens": status.month_tokens,
        "daily_budget": status.daily_budget,
        "over_budget": status.over_budget,
        "pct_used": status.pct_used,
        "workspace_today_tokens": workspace_today,
    }
