"""
ingestion/models.py
-------------------
Purpose:    ORM models for the ingestion pipeline entities.
            Document → IngestionJob tracks async processing.
            Chunk is the unit of retrieval and citation.
Dependencies: shared/database.py (Base), auth/models.py (Workspace FK), schema.md
Scope:      Model definitions only.

Key invariant (schema.md): every Chunk row has a vector in Turbovec; Postgres is
authoritative. chunk.turbovec_id is the join key between the two stores.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Enum, FetchedValue, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.settings import settings
from src.shared.database import Base

if TYPE_CHECKING:
    from src.auth.models import Workspace
    from src.research.models import Citation


class SourceType(enum.StrEnum):
    pdf = "pdf"
    repo = "repo"
    audio = "audio"


class JobStage(enum.StrEnum):
    queued = "queued"
    extracting = "extracting"
    chunking = "chunking"
    embedding = "embedding"
    done = "done"
    failed = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    # SHA-256 of the raw uploaded bytes — basis for dedup + idempotency. NULL for
    # legacy rows and for source types whose content isn't a single file blob.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # git URL for repos, filesystem path for uploads
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    # Path to raw file on disk (worker reads from here)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    # Mirrors the active ingestion_job stage for quick status checks
    processing_status: Mapped[JobStage] = mapped_column(
        Enum(JobStage), nullable=False, default=JobStage.queued
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workspace: Mapped[Workspace] = relationship(back_populates="documents")
    ingestion_job: Mapped[IngestionJob | None] = relationship(
        back_populates="document", uselist=False
    )
    chunks: Mapped[list[Chunk]] = relationship(back_populates="document")


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id"), nullable=False, unique=True
    )
    stage: Mapped[JobStage] = mapped_column(
        Enum(JobStage), nullable=False, default=JobStage.queued
    )
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-stage timestamps as JSONB: {"queued": "...", "extracting": "...", ...}
    stage_timestamps: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    document: Mapped[Document] = relationship(back_populates="ingestion_job")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    # Ordinal position within the document (for sorting citations)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Full text — Postgres is the source of truth (schema.md invariant)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Join key to Turbovec — same UUID string used as turbovec record id
    # ponytail: UUID is its own join key — no extra lookup table needed
    turbovec_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Dense embedding persisted in Postgres (pgvector). Source of truth for the
    # vector index — survives cold starts, no in-memory rebuild required.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.EMBEDDING_DIM), nullable=True
    )
    # Inherited metadata from document-level extraction (author, date, category, page, etc.)
    # ponytail: renamed from 'metadata' to avoid SQLAlchemy Base.metadata conflict
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Generated tsvector column for BM25 full-text search — computed by Postgres,
    # never written from Python. Read-only in the ORM (FetchedValue).
    tsv: Mapped[str | None] = mapped_column(server_default=FetchedValue(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="chunks")
    citations: Mapped[list[Citation]] = relationship(back_populates="chunk")