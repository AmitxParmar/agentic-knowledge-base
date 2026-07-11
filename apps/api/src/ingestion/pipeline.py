"""
ingestion/pipeline.py
---------------------
Six-stage ingestion pipeline run by arq.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import logfire
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import src.shared.models  # noqa: F401 — register all ORM models before any query
from src.ingestion.chunker import chunk_document
from src.ingestion.extractors import extract
from src.ingestion.models import Chunk, Document, IngestionJob, JobStage
from src.retrieval.embedder import embed_texts
from src.retrieval.vector_index import get_vector_index
from src.shared.database import SessionLocal

logger = logging.getLogger(__name__)


async def run_ingestion_job(ctx: dict[str, Any], *, document_id: str) -> None:
    del ctx
    doc_uuid = uuid.UUID(document_id)

    async with SessionLocal() as session:
        with logfire.span("ingestion.pipeline", document_id=document_id):
            try:
                await _run_pipeline(session, doc_uuid)
            except Exception as exc:
                logger.exception("ingestion pipeline failed for document %s", document_id)
                logfire.error("ingestion.failed", document_id=document_id, error=str(exc))
                await _mark_failed(session, doc_uuid, str(exc))
                raise


async def _run_pipeline(session: AsyncSession, document_id: uuid.UUID) -> None:
    doc = await _get_document(session, document_id)
    job = await _get_job(session, document_id)

    await _update_stage(session, doc, job, JobStage.extracting)
    with logfire.span("ingestion.extract", source_type=doc.source_type.value):
        content = extract(Path(doc.storage_path), source_type=doc.source_type.value)

    await _update_stage(session, doc, job, JobStage.chunking)
    with logfire.span("ingestion.chunk"):
        chunk_results = chunk_document(content, source_type=doc.source_type.value)

    if not chunk_results:
        raise ValueError(f"Extraction produced no chunks for document {document_id}")

    await _update_stage(session, doc, job, JobStage.embedding)
    with logfire.span("ingestion.embed", chunk_count=len(chunk_results)):
        vectors = await embed_texts([chunk.text for chunk in chunk_results])

    with logfire.span("ingestion.persist", chunk_count=len(chunk_results)):
        chunk_rows: list[tuple[Chunk, list[float]]] = []
        for chunk_result, vector in zip(chunk_results, vectors, strict=True):
            chunk_id = uuid.uuid4()
            chunk_row = Chunk(
                id=chunk_id,
                document_id=document_id,
                position=chunk_result.position,
                text=chunk_result.text,
                turbovec_id=str(chunk_id),
                chunk_metadata=chunk_result.metadata,
            )
            session.add(chunk_row)
            chunk_rows.append((chunk_row, vector))

        await session.flush()

        vector_index = get_vector_index()
        for chunk_row, vector in chunk_rows:
            vector_index.upsert(chunk_row.turbovec_id, vector)

    await _update_stage(session, doc, job, JobStage.done)
    logfire.info("ingestion.done", document_id=str(document_id), chunks=len(chunk_rows))


async def _get_document(session: AsyncSession, document_id: uuid.UUID) -> Document:
    result = await session.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise ValueError(f"Document {document_id} not found")
    return doc


async def _get_job(session: AsyncSession, document_id: uuid.UUID) -> IngestionJob:
    result = await session.execute(select(IngestionJob).where(IngestionJob.document_id == document_id))
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
