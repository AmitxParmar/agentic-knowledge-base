"""
ingestion/router.py
-------------------
Purpose: API endpoints for document upload and ingestion status.
Upload returns immediately while arq processes the job in the background.
"""

from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import arq
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import settings
from src.auth.stub import get_user_id, get_workspace_id
from src.ingestion.models import Document, IngestionJob, JobStage, SourceType
from src.shared.database import get_session
from src.shared.errors import NotFoundError

router = APIRouter()

UPLOAD_DIR = Path(settings.UPLOAD_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


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

    doc_id = uuid.uuid4()
    dest = UPLOAD_DIR / str(workspace_id) / f"{doc_id}_{file.filename}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    doc = Document(
        id=doc_id,
        workspace_id=workspace_id,
        source_type=SourceType(source_type),
        filename=file.filename or "upload",
        source_ref=str(dest),
        storage_path=str(dest),
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
    await redis.enqueue_job("run_ingestion_job", document_id=str(doc_id))
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
