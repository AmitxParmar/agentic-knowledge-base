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

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import logfire
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.stub import get_user_id, get_workspace_id
from src.research.agent import run_agent
from src.research.models import ResearchRun, RunStatus
from src.shared.database import get_session
from src.shared.progress import ResearchStage, emit, emit_done, emit_error

router = APIRouter()
logger = logging.getLogger(__name__)


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
            )

            # Update run with final answer
            run.answer = result.answer
            run.iteration_count = result.iterations
            run.status = RunStatus.complete
            run.completed_at = datetime.now(UTC)
            await session.commit()

        # Send the final answer with citations
        # Citations include source_ref for the UI to display (ux.md citation display requirement)
        await ws.send_text(json.dumps({
            "type": "answer",
            "run_id": str(run.id),
            "text": result.answer,
            "citations": [
                {
                    "chunk_id": c["chunk_id"],
                    "source_ref": c["source_ref"],
                    "relevance_score": round(c.get("relevance_score", 0.0), 4),
                }
                for c in result.citations
            ],
        }))
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
        await emit_error(ws, "An error occurred during the research run.")
        try:
            if run:
                run.status = RunStatus.failed
                await session.commit()
        except Exception:
            pass
        await ws.close()


class RunSummary(BaseModel):
    run_id: str
    question: str
    status: str
    created_at: str


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
        "citations": [{"chunk_id": str(c.chunk_id)} for c in run.citations],
        "created_at": run.created_at.isoformat(),
    }
