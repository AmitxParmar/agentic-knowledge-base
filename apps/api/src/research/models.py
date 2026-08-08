"""
research/models.py
------------------
Purpose:    ORM models for a research run and its citations.
            ResearchRun = one question → one answer session.
            Citation = traceability link between an answer claim and a chunk.
Dependencies: shared/database.py (Base), ingestion/models.py (Chunk FK), schema.md
Scope:      Model definitions only.

Key invariant (conventions.md citation-at-retrieval pattern):
Citations are written when chunks are retrieved, not reconstructed from the
final answer text. Every Citation row is born inside the Research Agent's
retrieval tool call.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.database import Base

if TYPE_CHECKING:
    from src.auth.models import Workspace
    from src.ingestion.models import Chunk


class RunStatus(enum.StrEnum):
    running = "running"
    complete = "complete"
    failed = "failed"


class ResearchRun(Base):
    __tablename__ = "research_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus), nullable=False, default=RunStatus.running
    )
    # Number of retrieval calls made (for the iteration bound check)
    iteration_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace: Mapped[Workspace] = relationship(back_populates="research_runs")
    citations: Mapped[list[Citation]] = relationship(back_populates="run")


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_runs.id"), nullable=False)
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chunks.id"), nullable=False)
    # Optional span: which part of the answer text this citation backs
    answer_span_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answer_span_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Relevance score at the time of retrieval (reranker output)
    relevance_score: Mapped[float | None] = mapped_column(nullable=True)

    run: Mapped[ResearchRun] = relationship(back_populates="citations")
    chunk: Mapped[Chunk] = relationship(back_populates="citations")


class ConversationThread(Base):
    """An ordered container that groups research_runs for history navigation.

    The runs themselves already persist their question/answer/citations; this
    table adds the thread container + title. Thread membership is derived
    client-side from the ordered list of run ids the thread stores, so the
    existing research-run write path (the agent) is untouched.
    """

    __tablename__ = "conversation_threads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="Untitled thread")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    workspace: Mapped[Workspace] = relationship(back_populates="conversation_threads")