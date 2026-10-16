"""
ingestion/router.py
-------------------
Purpose: API endpoints for document upload and ingestion status.
Upload returns immediately while arq processes the job in the background.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import uuid
from datetime import UTC, datetime

import arq
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from pypdf import PdfReader
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.settings import settings
from src.auth.stub import get_user_id, get_workspace_id
from src.ingestion.models import Chunk, Document, IngestionJob, JobStage, SourceType
from src.ingestion.pipeline import reset_job_for_retry
from src.ingestion.storage import delete_ref, store
from src.research.models import Citation
from src.shared.database import get_session
from src.shared.errors import NotFoundError
from src.shared.rate_limit import check_upload_rate_limit
from src.shared.retrieval_cache import invalidate_retrieval_cache
from src.shared.semantic_cache import SemanticCache

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


class FailedJobResponse(JobStatusResponse):
    filename: str


class FailedJobsResponse(BaseModel):
    jobs: list[FailedJobResponse]
    total: int


class RetryResponse(BaseModel):
    job_id: str
    document_id: str
    status: str
    message: str


class RebuildVectorsResponse(BaseModel):
    current_model: str
    stats: dict[str, int]
    stale_documents: list[str]
    requeued: list[str]
    message: str


async def _enqueue_ingestion_job(
    *, document_id: str, content_hash: str | None, request_id: str | None = None
) -> None:
    """Enqueue the arq ingestion job under a deterministic id.

    The _job_id pins re-delivery to one arq job per document content, so a
    manual retry and an at-least-once redelivery never double-enqueue.
    Content hash may be null on legacy rows — fall back to the document id.
    The request id rides along for log correlation (jobs have no HTTP scope).
    """
    # Step 1: open a short-lived pool (callers are request handlers, not workers).
    redis = await arq.create_pool(arq.connections.RedisSettings.from_dsn(settings.REDIS_URL))
    try:
        # Step 2: enqueue under the deterministic arq job id; close the pool either way.
        await redis.enqueue_job(
            "run_ingestion_job",
            document_id=document_id,
            request_id=request_id,
            _job_id=f"ingest:{content_hash or document_id}",
        )
    finally:
        await redis.close()


def _validate_pdf(raw: bytes, filename: str) -> None:
    """
    Validate uploaded PDF bytes. Raises HTTPException with a generic 4xx
    message — never leaks internal detail or stack traces.
    """
    if not raw:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    if len(raw) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE // (1024 * 1024)} MB.",
        )

    # Magic-byte check: every valid PDF starts with %PDF-
    if not raw[:5].startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="File does not appear to be a valid PDF.")

    # Try to open with pypdf for structural validation
    try:
        reader = PdfReader(io.BytesIO(raw))
    except Exception:
        raise HTTPException(status_code=422, detail="File could not be parsed as a PDF.") from None

    if reader.is_encrypted:
        raise HTTPException(
            status_code=422,
            detail="Encrypted PDFs are not supported. Please decrypt before uploading.",
        )

    page_count = len(reader.pages)
    if page_count == 0:
        raise HTTPException(status_code=422, detail="PDF has no pages.")

    if page_count > settings.MAX_PDF_PAGES:
        raise HTTPException(
            status_code=422,
            detail=f"PDF has {page_count} pages, which exceeds the maximum of {settings.MAX_PDF_PAGES}.",
        )


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    source_type: str = Form(..., description="pdf | repo | audio"),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user_id: uuid.UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
    _rate: None = Depends(check_upload_rate_limit),
) -> UploadResponse:
    """Accept upload, validate, persist rows, then enqueue the ingestion job."""
    del user_id  # ponytail: reserved for real auth later

    if source_type not in {"pdf", "repo", "audio"}:
        raise HTTPException(status_code=422, detail=f"Invalid source_type: {source_type!r}")

    # ── Content-Type validation ───────────────────────────────────────────────
    content_type = file.content_type or ""
    if source_type == "pdf" and content_type not in (
        "application/pdf",
        "application/octet-stream",
        "",
    ):
        raise HTTPException(
            status_code=422, detail="Content-Type must be application/pdf for PDF uploads."
        )

    # ── Read and validate ─────────────────────────────────────────────────────
    raw = await file.read()

    if source_type == "pdf":
        _validate_pdf(raw, file.filename or "upload")

    # ── Content-hash dedup + idempotency ──────────────────────────────────────
    content_hash = hashlib.sha256(raw).hexdigest()

    existing = await session.execute(
        select(Document)
        .where(
            Document.workspace_id == workspace_id,
            Document.content_hash == content_hash,
        )
        .options(selectinload(Document.ingestion_job))
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

    await _enqueue_ingestion_job(
        document_id=str(doc_id),
        content_hash=content_hash,
        request_id=getattr(request.state, "request_id", None),
    )

    return UploadResponse(
        document_id=str(doc_id),
        job_id=str(job.id),
        status="queued",
        message="Upload received. Processing started in background.",
    )


@router.get("/jobs/failed", response_model=FailedJobsResponse)
async def list_failed_jobs(
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
) -> FailedJobsResponse:
    """Dead-letter surface: jobs that exhausted arq retries, newest first.

    Failed rows stay queryable (with their error_detail) until re-enqueued
    or the document is deleted — nothing failure-related is silently dropped.
    NOTE: registered before /jobs/{job_id} so "failed" isn't parsed as an id.
    """
    # Step 1: join jobs to documents for workspace scoping + filenames.
    result = await session.execute(
        select(IngestionJob, Document)
        .join(Document, IngestionJob.document_id == Document.id)
        .where(
            Document.workspace_id == workspace_id,
            IngestionJob.stage == JobStage.failed,
        )
        .order_by(IngestionJob.id.desc())
        .limit(limit)
    )
    rows = result.all()
    # Step 2: shape the client payload.
    return FailedJobsResponse(
        jobs=[
            FailedJobResponse(
                job_id=str(job.id),
                document_id=str(job.document_id),
                stage=job.stage.value,
                error=job.error_detail,
                filename=doc.filename,
            )
            for job, doc in rows
        ],
        total=len(rows),
    )


@router.post("/jobs/{job_id}/retry", response_model=RetryResponse)
async def retry_failed_job(
    job_id: uuid.UUID,
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    session: AsyncSession = Depends(get_session),
) -> RetryResponse:
    """Re-enqueue a failed ingestion job after resetting its rows.

    Only failed jobs are retryable — anything else is a 409. The reset
    clears stale chunks/citations first, so the retry can never duplicate
    corpus rows even under at-least-once delivery.
    """
    # Step 1: load the job with its document, workspace-scoped (else 404 —
    # never confirm cross-workspace rows exist).
    result = await session.execute(
        select(IngestionJob, Document)
        .join(Document, IngestionJob.document_id == Document.id)
        .where(
            IngestionJob.id == job_id,
            Document.workspace_id == workspace_id,
        )
    )
    row = result.one_or_none()
    if row is None:
        raise NotFoundError(f"Job {job_id} not found in workspace")
    job, doc = row
    # Step 2: refuse non-failed jobs — retry is a dead-letter action only.
    if job.stage != JobStage.failed:
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} is in stage {job.stage.value}, not failed.",
        )
    # Step 3: rewind rows to queued (clears stale chunks/citations).
    await reset_job_for_retry(session, job, doc)
    # Step 4: re-enqueue under the same deterministic arq job id.
    await _enqueue_ingestion_job(document_id=str(doc.id), content_hash=doc.content_hash)
    return RetryResponse(
        job_id=str(job.id),
        document_id=str(doc.id),
        status=JobStage.queued.value,
        message="Job re-queued for ingestion.",
    )


@router.post("/admin/rebuild-vectors", response_model=RebuildVectorsResponse)
async def rebuild_vectors(
    apply: bool = Query(
        default=False,
        description="When true, reset + re-enqueue every document with stale vectors",
    ),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    session: AsyncSession = Depends(get_session),
) -> RebuildVectorsResponse:
    """Debug-only vector rebuild: re-embed documents on a stale embedding model.

    Hidden (404) unless APP_DEBUG — same rule as /test-llm. With apply=false
    this is a read-only report (per-model chunk counts); with apply=true each
    stale document is rewound via reset_job_for_retry and re-enqueued, so the
    normal pipeline re-embeds it under the current model (no duplicates —
    the reset deletes old chunks first).
    """
    # Step 1: debug-only — invisible in production like /test-llm.
    if not settings.APP_DEBUG:
        raise NotFoundError("Not found")
    from src.retrieval.embedder import embedding_model_label

    current = embedding_model_label()
    # Step 2: per-model chunk counts, workspace-scoped (NULL = pre-tracking).
    stats_result = await session.execute(
        select(Chunk.embedding_model, func.count(Chunk.id))
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.workspace_id == workspace_id)
        .group_by(Chunk.embedding_model)
    )
    stats = {(row[0] or "unversioned"): row[1] for row in stats_result.all()}
    # Step 3: documents holding at least one stale (non-current/NULL) chunk.
    stale_result = await session.execute(
        select(Document.id)
        .join(Chunk, Chunk.document_id == Document.id)
        .where(
            Document.workspace_id == workspace_id,
            (Chunk.embedding_model.is_(None)) | (Chunk.embedding_model != current),
        )
        .distinct()
    )
    stale_documents = [str(row[0]) for row in stale_result.all()]
    # Step 4: dry run by default — only report.
    requeued: list[str] = []
    if not apply:
        return RebuildVectorsResponse(
            current_model=current,
            stats=stats,
            stale_documents=stale_documents,
            requeued=requeued,
            message=f"{len(stale_documents)} document(s) on stale vectors; re-run with apply=true.",
        )
    # Step 5: rewind + re-enqueue each stale document through the normal path.
    for doc_id in stale_documents:
        row = await session.execute(
            select(IngestionJob, Document)
            .join(Document, IngestionJob.document_id == Document.id)
            .where(
                IngestionJob.document_id == uuid.UUID(doc_id),
                Document.workspace_id == workspace_id,
            )
        )
        job_doc = row.one_or_none()
        if job_doc is None:
            continue
        job, doc = job_doc
        await reset_job_for_retry(session, job, doc)
        await _enqueue_ingestion_job(
            document_id=str(doc.id),
            content_hash=doc.content_hash,
            request_id=None,
        )
        requeued.append(str(doc.id))
    return RebuildVectorsResponse(
        current_model=current,
        stats=stats,
        stale_documents=stale_documents,
        requeued=requeued,
        message=f"Re-queued {len(requeued)} document(s) for re-embedding under {current}.",
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
    processing_status: str | None = Query(
        default=None, description="Filter by processing status, e.g. done"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DocumentListResponse:
    """List documents in the workspace, newest first, paginated. Optionally filter by processing status."""
    conditions = [Document.workspace_id == workspace_id]
    if processing_status is not None:
        conditions.append(Document.processing_status == processing_status)

    count_result = await session.execute(select(func.count(Document.id)).where(*conditions))
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
    result = await session.execute(
        select(Chunk).where(Chunk.id == chunk_id).options(selectinload(Chunk.document))
    )
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

    # Delete in FK dependency order: citations → chunks → ingestion_job → document.
    await session.execute(
        delete(Citation).where(
            Citation.chunk_id.in_(select(Chunk.id).where(Chunk.document_id == document_id))
        )
    )
    await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
    await session.execute(delete(IngestionJob).where(IngestionJob.document_id == document_id))
    await session.execute(
        delete(Document).where(
            Document.id == document_id,
            Document.workspace_id == workspace_id,
        )
    )

    # The corpus changed → cached answers and retrievals for this workspace are
    # stale (ADR-007). Best-effort: a Redis failure must not fail the delete.
    with contextlib.suppress(Exception):
        await SemanticCache().invalidate_workspace(str(workspace_id))
        await invalidate_retrieval_cache(str(workspace_id))

    # Orphan cleanup: remove the raw upload too — rows alone would leak disk
    # (or R2 storage). Best-effort like the cache invalidation above.
    with contextlib.suppress(Exception):
        delete_ref(doc.storage_path or doc.source_ref)
