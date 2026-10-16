"""
tests/ingestion/test_rebuild_vectors.py
----------------------------------------
Purpose:    Debug-only vector rebuild endpoint: dry-run stats (per-model
            chunk counts + stale documents) and apply mode (reset +
            re-enqueue stale documents). Hidden with 404 unless APP_DEBUG.
Dependencies: pytest, FastAPI TestClient. DB/arq are mocked.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ingestion.models import JobStage


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


def _enable_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "APP_DEBUG", True)
    monkeypatch.setattr(
        "src.retrieval.embedder.embedding_model_label",
        lambda: "cohere:embed-v3",
    )


def test_rebuild_hidden_without_debug(
    app_client: tuple[TestClient, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production (APP_DEBUG off) must not expose the endpoint."""
    from app.settings import settings

    monkeypatch.setattr(settings, "APP_DEBUG", False)
    client, _ = app_client
    resp = client.post("/api/ingestion/admin/rebuild-vectors")
    assert resp.status_code == 404


def test_rebuild_dry_run_reports_stats(
    app_client: tuple[TestClient, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dry run: per-model counts + stale list, nothing re-queued."""
    _enable_debug(monkeypatch)
    client, session = app_client

    stale_doc = uuid.uuid4()
    stats_result = MagicMock()
    stats_result.all = MagicMock(return_value=[("cohere:embed-v3", 5), (None, 3)])
    stale_result = MagicMock()
    stale_result.all = MagicMock(return_value=[(stale_doc,)])
    session.execute = AsyncMock(side_effect=[stats_result, stale_result])

    resp = client.post("/api/ingestion/admin/rebuild-vectors")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_model"] == "cohere:embed-v3"
    assert body["stats"] == {"cohere:embed-v3": 5, "unversioned": 3}
    assert body["stale_documents"] == [str(stale_doc)]
    assert body["requeued"] == []


def test_rebuild_apply_requeues_stale_docs(
    app_client: tuple[TestClient, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apply mode: each stale document is rewound and re-enqueued."""
    _enable_debug(monkeypatch)
    client, session = app_client

    doc_id = uuid.uuid4()
    job = SimpleNamespace(
        id=uuid.uuid4(),
        document_id=doc_id,
        stage=JobStage.done,
        error_detail=None,
        stage_timestamps={},
    )
    doc = SimpleNamespace(
        id=doc_id,
        workspace_id=uuid.uuid4(),
        filename="report.pdf",
        content_hash="def456",
        processing_status=JobStage.done,
    )
    stats_result = MagicMock()
    stats_result.all = MagicMock(return_value=[("old-model", 2)])
    stale_result = MagicMock()
    stale_result.all = MagicMock(return_value=[(doc_id,)])
    job_result = MagicMock()
    job_result.one_or_none = MagicMock(return_value=(job, doc))
    # reset_job_for_retry issues two more executes (citations, chunks deletes).
    reset_citations = MagicMock(rowcount=0)
    reset_chunks = MagicMock(rowcount=0)
    session.execute = AsyncMock(
        side_effect=[stats_result, stale_result, job_result, reset_citations, reset_chunks]
    )

    with patch(
        "src.ingestion.router._enqueue_ingestion_job", new_callable=AsyncMock
    ) as mock_enqueue:
        resp = client.post("/api/ingestion/admin/rebuild-vectors?apply=true")

    assert resp.status_code == 200
    body = resp.json()
    assert body["requeued"] == [str(doc_id)]
    assert job.stage == JobStage.queued
    mock_enqueue.assert_awaited_once()
    _, kwargs = mock_enqueue.call_args
    assert kwargs["document_id"] == str(doc_id)
    assert kwargs["content_hash"] == "def456"
