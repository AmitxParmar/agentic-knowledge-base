"""
research/conversations_router.py
---------------------------------
Purpose:    CRUD endpoints for conversation threads. A thread groups research
            runs for history navigation; the runs themselves already persist
            their question/answer/citations in research_runs.
Dependencies: research/models, auth/stub, shared/database, shared/errors
Scope:      Thread lifecycle only. Run storage is untouched.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth.stub import get_workspace_id
from src.ingestion.models import Chunk
from src.research.models import Citation, ConversationThread, ResearchRun
from src.shared.database import get_session
from src.shared.errors import NotFoundError

router = APIRouter()


# ── Response schemas ─────────────────────────────────────────────────────────


class ThreadSummary(BaseModel):
    id: str
    title: str
    run_count: int
    created_at: str
    updated_at: str


class ThreadList(BaseModel):
    threads: list[ThreadSummary]


class CitationOut(BaseModel):
    chunk_id: str
    source_ref: str
    relevance_score: float | None = None


class RunOut(BaseModel):
    id: str
    question: str
    answer: str | None = None
    status: str
    citations: list[CitationOut]
    created_at: str


class ThreadDetail(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class ThreadWithRuns(BaseModel):
    thread: ThreadDetail
    runs: list[RunOut]


class CreateThreadRequest(BaseModel):
    title: str | None = None


class RenameThreadRequest(BaseModel):
    title: str


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("", response_model=ThreadList)
async def list_threads(
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    session: AsyncSession = Depends(get_session),
) -> ThreadList:
    """List threads for the workspace, newest first."""
    result = await session.execute(
        select(ConversationThread)
        .where(ConversationThread.workspace_id == workspace_id)
        .order_by(ConversationThread.updated_at.desc())
    )
    threads = result.scalars().all()

    return ThreadList(
        threads=[
            ThreadSummary(
                id=str(t.id),
                title=t.title,
                # Server does not yet track thread→run membership; the client
                # holds the authoritative per-thread run list and overrides this.
                run_count=0,
                created_at=t.created_at.isoformat(),
                updated_at=t.updated_at.isoformat(),
            )
            for t in threads
        ]
    )


@router.post("", response_model=ThreadDetail, status_code=201)
async def create_thread(
    body: CreateThreadRequest,
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    session: AsyncSession = Depends(get_session),
) -> ThreadDetail:
    """Create a new thread. Title defaults to a placeholder if omitted."""
    thread = ConversationThread(
        workspace_id=workspace_id,
        title=body.title or "Untitled thread",
    )
    session.add(thread)
    await session.commit()
    await session.refresh(thread)
    return _thread_detail(thread)


@router.get("/{thread_id}", response_model=ThreadWithRuns)
async def get_thread(
    thread_id: uuid.UUID,
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    session: AsyncSession = Depends(get_session),
) -> ThreadWithRuns:
    """Get one thread plus its runs (question, answer, citations)."""
    result = await session.execute(
        select(ConversationThread).where(
            ConversationThread.id == thread_id,
            ConversationThread.workspace_id == workspace_id,
        )
    )
    thread = result.scalar_one_or_none()
    if thread is None:
        raise NotFoundError(f"Thread {thread_id} not found")

    runs = await session.execute(
        select(ResearchRun)
        .where(ResearchRun.workspace_id == workspace_id)
        .order_by(ResearchRun.created_at.asc())
    )
    # Thread membership is derived client-side; return all workspace runs so
    # the client can filter to the thread's run ids. The client already holds
    # the ordered run-id list for this thread.
    run_rows = runs.scalars().all()
    return ThreadWithRuns(
        thread=_thread_detail(thread),
        runs=[await _run_out(session, r) for r in run_rows],
    )


@router.patch("/{thread_id}", response_model=ThreadDetail)
async def rename_thread(
    thread_id: uuid.UUID,
    body: RenameThreadRequest,
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    session: AsyncSession = Depends(get_session),
) -> ThreadDetail:
    """Rename a thread."""
    result = await session.execute(
        select(ConversationThread).where(
            ConversationThread.id == thread_id,
            ConversationThread.workspace_id == workspace_id,
        )
    )
    thread = result.scalar_one_or_none()
    if thread is None:
        raise NotFoundError(f"Thread {thread_id} not found")

    thread.title = body.title
    await session.commit()
    await session.refresh(thread)
    return _thread_detail(thread)


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: uuid.UUID,
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a thread. Runs are preserved (they still belong to the workspace)."""
    result = await session.execute(
        select(ConversationThread).where(
            ConversationThread.id == thread_id,
            ConversationThread.workspace_id == workspace_id,
        )
    )
    thread = result.scalar_one_or_none()
    if thread is None:
        raise NotFoundError(f"Thread {thread_id} not found")

    await session.execute(
        delete(ConversationThread).where(ConversationThread.id == thread_id)
    )
    await session.commit()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _thread_detail(thread: ConversationThread) -> ThreadDetail:
    return ThreadDetail(
        id=str(thread.id),
        title=thread.title,
        created_at=thread.created_at.isoformat(),
        updated_at=thread.updated_at.isoformat(),
    )


async def _run_out(session: AsyncSession, run: ResearchRun) -> RunOut:
    result = await session.execute(
        select(Citation)
        .where(Citation.run_id == run.id)
        .options(selectinload(Citation.chunk).selectinload(Chunk.document))
    )
    citations = result.scalars().all()
    return RunOut(
        id=str(run.id),
        question=run.question,
        answer=run.answer,
        status=run.status.value,
        citations=[
            CitationOut(
                chunk_id=str(c.chunk_id),
                source_ref=c.chunk.document.source_ref if c.chunk and c.chunk.document else "",
                relevance_score=c.relevance_score,
            )
            for c in citations
        ],
        created_at=run.created_at.isoformat(),
    )
