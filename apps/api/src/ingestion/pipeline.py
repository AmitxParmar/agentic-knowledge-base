"""
ingestion/pipeline.py
---------------------
Six-stage ingestion pipeline run by arq.
PDF extraction runs in a thread pool under a semaphore with a hard timeout.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import logfire
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

import src.shared.models  # noqa: F401 — register all ORM models before any query
from app.settings import settings
from src.ingestion.chunker import chunk_document
from src.ingestion.extractors import extract
from src.ingestion.models import Chunk, Document, IngestionJob, JobStage
from src.ingestion.storage import open_ref
from src.observability.setup import traced_observation
from src.research.models import Citation
from src.retrieval.embedder import embed_texts, embedding_model_label
from src.shared.database import SessionLocal
from src.shared.rate_limit import indexing_semaphore, pdf_parse_semaphore
from src.shared.retrieval_cache import invalidate_retrieval_cache
from src.shared.semantic_cache import SemanticCache

logger = logging.getLogger(__name__)

# One shared executor for blocking PDF work. 2 threads matches the semaphore limit
# so a third parse never waits in the thread pool queue.
_pdf_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pdf-parse")


async def run_ingestion_job(ctx: dict[str, Any], *, document_id: str) -> None:
    del ctx
    doc_uuid = uuid.UUID(document_id)

    async with SessionLocal() as session:
        # One trace per ingested document ("one pipeline execution" per the
        # Langfuse trace-scope guidance); embed-texts children nest beneath it.
        with traced_observation(
            "ingest-document",
            input={"document_id": document_id},
        ) as observation:
            with logfire.span("ingestion.pipeline", document_id=document_id):
                try:
                    async with indexing_semaphore():
                        chunk_count = await _run_pipeline(session, doc_uuid)
                except Exception as exc:
                    logger.exception("ingestion pipeline failed for document %s", document_id)
                    logfire.error("ingestion.failed", document_id=document_id, error=str(exc))
                    await _mark_failed(session, doc_uuid, str(exc))
                    raise
            observation.update(output={"chunks": chunk_count})


async def _run_pipeline(session: AsyncSession, document_id: uuid.UUID) -> int:
    doc = await _get_document(session, document_id)
    job = await _get_job(session, document_id)

    await _update_stage(session, doc, job, JobStage.extracting)
    with logfire.span("ingestion.extract", source_type=doc.source_type.value):
        source_path = open_ref(doc.storage_path)
        try:
            content = await _extract_with_timeout(source_path, doc.source_type.value)
        finally:
            if settings.r2_enabled and doc.storage_path.startswith("uploads/"):
                source_path.unlink(missing_ok=True)

    await _update_stage(session, doc, job, JobStage.chunking)
    with logfire.span("ingestion.chunk"):
        chunk_results = chunk_document(content, source_type=doc.source_type.value)

    # Drop blank chunks (Chonkie can emit whitespace-only segments on empty pages).
    # Without this, embed_texts would sanitize to " " and waste Cohere quota,
    # and we'd persist meaningless vectors. Keep at least one non-blank chunk.
    chunk_results = [c for c in chunk_results if c.text and c.text.strip()]
    if not chunk_results:
        raise ValueError(f"Extraction produced no chunks for document {document_id}")

    await _update_stage(session, doc, job, JobStage.embedding)
    with logfire.span("ingestion.embed", chunk_count=len(chunk_results)):
        vectors = await embed_texts([chunk.text for chunk in chunk_results])

    with logfire.span("ingestion.persist", chunk_count=len(chunk_results)):
        # Step 0: clear rows from any previous attempt. Without this, a retry
        # that runs after a committed run re-inserts every chunk with fresh
        # ids (at-least-once arq delivery) — silent corpus duplication.
        cleared = await reset_document_chunks(session, document_id)
        if cleared:
            logfire.info(
                "ingestion.reingest_cleared",
                document_id=str(document_id),
                cleared_chunks=cleared,
            )
        chunk_rows: list[Chunk] = []
        # Step 0c: stamp every row with the embedding provenance for this
        # process config — mixed models in one vector column degrade
        # similarity silently, so the label travels with the vector.
        embed_model = embedding_model_label()
        for chunk_result, vector in zip(chunk_results, vectors, strict=True):
            chunk_id = uuid.uuid4()
            chunk_row = Chunk(
                id=chunk_id,
                document_id=document_id,
                position=chunk_result.position,
                text=chunk_result.text,
                turbovec_id=str(chunk_id),
                embedding=vector,
                embedding_model=embed_model,
                chunk_metadata=chunk_result.metadata,
            )
            session.add(chunk_row)
            chunk_rows.append(chunk_row)

        await session.flush()

    await _update_stage(session, doc, job, JobStage.done)
    # The corpus changed → previously cached answers and retrievals are stale.
    await SemanticCache().invalidate_workspace(str(doc.workspace_id))
    await invalidate_retrieval_cache(str(doc.workspace_id))
    logfire.info("ingestion.done", document_id=str(document_id), chunks=len(chunk_rows))
    return len(chunk_rows)


async def reset_document_chunks(session: AsyncSession, document_id: uuid.UUID) -> int:
    """Delete a document's chunks (and their citations) before a (re-)ingest.

    Citation rows point at chunk ids, so they go first or the chunk delete
    violates the FK. Returns the number of chunk rows removed (0 on a clean
    first ingest). Makes every pipeline stage re-runnable under arq's
    at-least-once delivery.
    """
    # Step 1: citations reference chunk ids — remove them first (FK order).
    await session.execute(
        delete(Citation).where(
            Citation.chunk_id.in_(select(Chunk.id).where(Chunk.document_id == document_id))
        )
    )
    # Step 2: the chunks themselves; fresh ids are minted on re-insert.
    result = await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
    await session.flush()
    return getattr(result, "rowcount", 0) or 0


async def reset_job_for_retry(session: AsyncSession, job: IngestionJob, doc: Document) -> int:
    """Reset a failed job + document to queued for manual re-enqueue.

    Clears stale chunks/citations, wipes the failure, and recommits — the
    caller re-enqueues the arq job afterwards. Returns cleared chunk count.
    """
    # Step 1: clear stale output rows so the retry starts from a clean corpus.
    cleared = await reset_document_chunks(session, doc.id)
    # Step 2: rewind job + document to queued with a fresh timestamp trail.
    now = datetime.now(UTC).isoformat()
    job.stage = JobStage.queued
    job.error_detail = None
    job.stage_timestamps = {JobStage.queued.value: now}
    doc.processing_status = JobStage.queued
    await session.commit()
    logfire.info(
        "ingestion.retry_reset",
        document_id=str(doc.id),
        job_id=str(job.id),
        cleared_chunks=cleared,
    )
    return cleared


async def _extract_with_timeout(source_path: Any, source_type: str) -> Any:
    """
    Run extract() in a thread pool under the PDF parse semaphore.
    Times out after PDF_PARSE_TIMEOUT seconds; raises asyncio.TimeoutError.
    """
    loop = asyncio.get_running_loop()

    async def _do() -> Any:
        async with pdf_parse_semaphore():
            return await loop.run_in_executor(
                _pdf_executor,
                lambda: extract(source_path, source_type),
            )

    return await asyncio.wait_for(_do(), timeout=settings.PDF_PARSE_TIMEOUT)


async def _get_document(session: AsyncSession, document_id: uuid.UUID) -> Document:
    result = await session.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise ValueError(f"Document {document_id} not found")
    return doc


async def _get_job(session: AsyncSession, document_id: uuid.UUID) -> IngestionJob:
    result = await session.execute(
        select(IngestionJob).where(IngestionJob.document_id == document_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise ValueError(f"IngestionJob for document {document_id} not found")
    return job


async def _update_stage(
    session: AsyncSession,
    doc: Document,
    job: IngestionJob,
    stage: JobStage,
) -> None:
    now = datetime.now(UTC).isoformat()
    job.stage = stage
    job.stage_timestamps = {**job.stage_timestamps, stage.value: now}
    doc.processing_status = stage
    await session.commit()
    logfire.info("ingestion.stage", stage=stage.value, document_id=str(doc.id))


async def _mark_failed(session: AsyncSession, document_id: uuid.UUID, error: str) -> None:
    try:
        doc = await _get_document(session, document_id)
        job = await _get_job(session, document_id)
        job.stage = JobStage.failed
        job.error_detail = error
        job.stage_timestamps = {
            **job.stage_timestamps,
            JobStage.failed.value: datetime.now(UTC).isoformat(),
        }
        doc.processing_status = JobStage.failed
        await session.commit()
    except Exception:
        logger.exception("could not mark document %s as failed", document_id)
