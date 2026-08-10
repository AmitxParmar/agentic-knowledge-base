"""
ingestion/router.py
-------------------
Purpose: API endpoints for document upload and ingestion status.
Upload returns immediately while arq processes the job in the background.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import arq
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import settings
from src.auth.stub import get_user_id, get_workspace_id
from src.ingestion.models import Chunk, Document, IngestionJob, JobStage, SourceType
from src.ingestion.storage import store
from src.shared.database import get_session
from src.shared.errors import NotFoundError

router = APIRouter()


class UploadResponse(BaseModel):
    document_id: str
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    document_id: str
    stage: str
    error: str | None = None


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    source_type: str = Form(..., description="pdf | repo | audio"),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user_id: uuid.UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
) -> UploadResponse:
    """Accept upload, persist rows, then enqueue the ingestion job."""
    del user_id  # ponytail: reserved for real auth later

    if source_type not in {"pdf", "repo", "audio"}:
        raise HTTPException(status_code=422, detail=f"Invalid source_type: {source_type!r}")

    # ── Content-hash dedup + idempotency ──────────────────────────────────────
    # Hash the raw bytes before any storage or enqueue. A re-upload of the same
    # file in the same workspace returns the existing job instead of spinning up
    # a second ingestion (and a second round of embedding spend).
    raw = await file.read()
    content_hash = hashlib.sha256(raw).hexdigest()

    existing = await session.execute(
        select(Document).where(
            Document.workspace_id == workspace_id,
            Document.content_hash == content_hash,
        )
    )
    dup = existing.scalar_one_or_none()
    if dup is not None:
        job = dup.ingestion_job
        return UploadResponse(
            document_id=str(dup.id),
            job_id=str(job.id) if job else str(uuid.uuid4()),
            status=dup.processing_status.value,
            message="Duplicate of an already-uploaded document — returning its existing job.",
        )

    doc_id = uuid.uuid4()
    # Durable storage (R2 when configured, local otherwise) — returns a ref
    # that ingestion reads back later. Never point at Render's ephemeral disk.
    storage_ref = store(
        raw,
        workspace_id=workspace_id,
        document_id=doc_id,
        filename=file.filename or "upload",
    )

    doc = Document(
        id=doc_id,
        workspace_id=workspace_id,
        source_type=SourceType(source_type),
        filename=file.filename or "upload",
        content_hash=content_hash,
        source_ref=storage_ref,
        storage_path=storage_ref,
        processing_status=JobStage.queued,
    )
    session.add(doc)
    await session.flush()

    job = IngestionJob(
        document_id=doc_id,
        stage=JobStage.queued,
        stage_timestamps={JobStage.queued.value: datetime.now(UTC).isoformat()},
    )
    session.add(job)
    await session.commit()

    redis = await arq.create_pool(arq.connections.RedisSettings.from_dsn(settings.REDIS_URL))
    # Idempotency key = content hash. If the same bytes are enqueued twice
    # (e.g. client retry), arq drops the duplicate instead of double-processing.
    await redis.enqueue_job(
        "run_ingestion_job",
        document_id=str(doc_id),
        _job_id=f"ingest:{content_hash}",
    )
    await redis.close()

    return UploadResponse(
        document_id=str(doc_id),
        job_id=str(job.id),
        status="queued",
        message="Upload received. Processing started in background.",
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> JobStatusResponse:
    result = await session.execute(select(IngestionJob).where(IngestionJob.id == job_id))
    job = result.scalar_one_or_none()

    if job is None:
        raise NotFoundError(f"Job {job_id} not found")

    return JobStatusResponse(
        job_id=str(job.id),
        document_id=str(job.document_id),
        stage=job.stage.value,
        error=job.error_detail,
    )


# ── List / read / delete endpoints (Phase 2) ─────────────────────────────────


class DocumentResponse(BaseModel):
    document_id: str
    source_type: str
    filename: str
    processing_status: str
    created_at: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


class ChunkResponse(BaseModel):
    chunk_id: str
    document_id: str
    source_ref: str
    text: str
    position: int


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    session: AsyncSession = Depends(get_session),
    processing_status: str | None = Query(default=None, description="Filter by processing status, e.g. done"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DocumentListResponse:
    """List documents in the workspace, newest first, paginated. Optionally filter by processing status."""
    conditions = [Document.workspace_id == workspace_id]
    if processing_status is not None:
        conditions.append(Document.processing_status == processing_status)

    count_result = await session.execute(
        select(func.count(Document.id)).where(*conditions)
    )
    total = count_result.scalar_one()

    result = await session.execute(
        select(Document)
        .where(*conditions)
        .order_by(Document.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    documents = result.scalars().all()

    return DocumentListResponse(
        documents=[
            DocumentResponse(
                document_id=str(doc.id),
                source_type=doc.source_type.value,
                filename=doc.filename,
                processing_status=doc.processing_status.value,
                created_at=doc.created_at.isoformat(),
            )
            for doc in documents
        ],
        total=total,
    )


@router.get("/chunks/{chunk_id}", response_model=ChunkResponse)
async def get_chunk(
    chunk_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ChunkResponse:
    """Fetch a single chunk's full text by ID."""
    result = await session.execute(select(Chunk).where(Chunk.id == chunk_id))
    chunk = result.scalar_one_or_none()

    if chunk is None:
        raise NotFoundError(f"Chunk {chunk_id} not found")

    return ChunkResponse(
        chunk_id=str(chunk.id),
        document_id=str(chunk.document_id),
        source_ref=chunk.document.source_ref,
        text=chunk.text,
        position=chunk.position,
    )


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a document and cascade to its chunks."""
    result = await session.execute(
        select(Document).where(
            Document.id == document_id,
            Document.workspace_id == workspace_id,
        )
    )
    doc = result.scalar_one_or_none()

    if doc is None:
        raise NotFoundError(f"Document {document_id} not found in workspace")

    await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
    await session.execute(
        delete(Document).where(
            Document.id == document_id,
            Document.workspace_id == workspace_id,
        )
    )
