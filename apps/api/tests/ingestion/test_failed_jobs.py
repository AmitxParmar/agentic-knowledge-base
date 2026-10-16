"""
tests/ingestion/test_failed_jobs.py
------------------------------------
Dead-letter queue: failed-job listing, manual retry, and re-runnable
ingest stages (delete-before-insert). DB/Redis/arq are mocked.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Delete

from src.ingestion.models import JobStage
from src.ingestion.pipeline import reset_document_chunks, reset_job_for_retry


@pytest.fixture()
def app_client():
    """Test app with mocked session/deps, mirroring production wiring."""
    import src.shared.models  # noqa: F401 — register ORM models before mapper resolution
    from src.ingestion.router import router
    from src.shared.errors import register_error_handlers

    app = FastAPI()
    app.include_router(router, prefix="/api/ingestion")
    register_error_handlers(app)

    from src.auth.stub import get_user_id, get_workspace_id
    from src.shared.database import get_session

    fixed_workspace = uuid.uuid4()

    session = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    async def _fake_session():
        yield session

    app.dependency_overrides[get_workspace_id] = lambda: fixed_workspace
    app.dependency_overrides[get_user_id] = lambda: uuid.uuid4()
    app.dependency_overrides[get_session] = _fake_session

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, session


def _job_doc(stage: JobStage) -> tuple[Any, Any]:
    # Step 1: fake a job row joined to its document row.
    job = SimpleNamespace(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        stage=stage,
        error_detail="boom" if stage == JobStage.failed else None,
        stage_timestamps={},
    )
    doc = SimpleNamespace(
        id=job.document_id,
        workspace_id=uuid.uuid4(),
        filename="report.pdf",
        content_hash="abc123",
        processing_status=stage,
    )
    return job, doc


# ── reset_document_chunks ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reset_deletes_citations_then_chunks() -> None:
    # Step 1: fake a chunk delete removing 3 rows.
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(rowcount=2),  # citations delete
            MagicMock(rowcount=3),  # chunks delete
        ]
    )
    session.flush = AsyncMock()
    # Step 2: FK order (citations first) + chunk count returned.
    assert await reset_document_chunks(session, uuid.uuid4()) == 3
    assert session.execute.await_count == 2
    second_stmt = session.execute.await_args_list[1].args[0]
    assert isinstance(second_stmt, Delete)


# ── reset_job_for_retry ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reset_job_rewinds_to_queued() -> None:
    job, doc = _job_doc(JobStage.failed)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(rowcount=0))
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    # Step 1: reset rewinds rows and recommits.
    await reset_job_for_retry(session, job, doc)
    assert job.stage == JobStage.queued
    assert job.error_detail is None
    assert doc.processing_status == JobStage.queued
    session.commit.assert_awaited_once()


# ── GET /jobs/failed ──────────────────────────────────────────────────────────


def test_list_failed_jobs(app_client: tuple[TestClient, Any]) -> None:
    client, session = app_client
    job, doc = _job_doc(JobStage.failed)
    result = MagicMock()
    result.all = MagicMock(return_value=[(job, doc)])
    session.execute = AsyncMock(return_value=result)
    # Step 1: the dead-letter list surfaces the failed job with its error.
    resp = client.get("/api/ingestion/jobs/failed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["jobs"][0]["job_id"] == str(job.id)
    assert body["jobs"][0]["stage"] == "failed"
    assert body["jobs"][0]["error"] == "boom"
    assert body["jobs"][0]["filename"] == "report.pdf"


def test_list_failed_jobs_empty(app_client: tuple[TestClient, Any]) -> None:
    client, session = app_client
    result = MagicMock()
    result.all = MagicMock(return_value=[])
    session.execute = AsyncMock(return_value=result)
    resp = client.get("/api/ingestion/jobs/failed")
    assert resp.status_code == 200
    assert resp.json() == {"jobs": [], "total": 0}


# ── POST /jobs/{id}/retry ─────────────────────────────────────────────────────


def _retry(client: TestClient, job_id: uuid.UUID):
    with patch("arq.create_pool", new_callable=AsyncMock) as mock_pool:
        mock_redis = AsyncMock()
        mock_redis.enqueue_job = AsyncMock()
        mock_redis.close = AsyncMock()
        mock_pool.return_value = mock_redis
        resp = client.post(f"/api/ingestion/jobs/{job_id}/retry")
        return resp, mock_redis


def test_retry_failed_job_requeues(app_client: tuple[TestClient, Any]) -> None:
    client, session = app_client
    job, doc = _job_doc(JobStage.failed)
    result = MagicMock()
    result.one_or_none = MagicMock(return_value=(job, doc))
    session.execute = AsyncMock(return_value=result)
    # Step 1: retry rewinds the rows and re-enqueues under the content hash.
    resp, mock_redis = _retry(client, job.id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "queued"
    assert job.stage == JobStage.queued
    mock_redis.enqueue_job.assert_awaited_once()
    _, kwargs = mock_redis.enqueue_job.call_args
    assert kwargs["document_id"] == str(doc.id)
    assert kwargs["_job_id"] == "ingest:abc123"


def test_retry_non_failed_job_conflicts(app_client: tuple[TestClient, Any]) -> None:
    client, session = app_client
    job, _doc = _job_doc(JobStage.embedding)
    result = MagicMock()
    result.one_or_none = MagicMock(return_value=(job, SimpleNamespace(id=job.document_id)))
    session.execute = AsyncMock(return_value=result)
    # Step 1: only dead-letter jobs are retryable.
    resp, _ = _retry(client, job.id)
    assert resp.status_code == 409


def test_retry_missing_job_404(app_client: tuple[TestClient, Any]) -> None:
    client, session = app_client
    result = MagicMock()
    result.one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    resp, _ = _retry(client, uuid.uuid4())
    assert resp.status_code == 404
