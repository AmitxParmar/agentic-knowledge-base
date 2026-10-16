"""
tests/ingestion/test_delete_cleanup.py
---------------------------------------
Orphan cleanup: deleting a document must remove its raw upload (local file
or R2 object), not just its DB rows. Redis/cache invalidation is mocked.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.settings import settings
from src.ingestion.storage import delete_ref


@pytest.fixture()
def app_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Test app with mocked session/deps; R2 forced off for local-file mode."""
    import src.shared.models  # noqa: F401 — register ORM models before mapper resolution
    from src.ingestion.router import router

    # Force the local storage path (dev .env may point at R2).
    monkeypatch.setattr(settings, "R2_ENDPOINT", "")

    app = FastAPI()
    app.include_router(router, prefix="/api/ingestion")

    from src.auth.stub import get_user_id, get_workspace_id
    from src.shared.database import get_session

    fixed_workspace = uuid.uuid4()

    session = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    async def _fake_session():
        yield session

    app.dependency_overrides[get_workspace_id] = lambda: fixed_workspace
    app.dependency_overrides[get_user_id] = lambda: uuid.uuid4()
    app.dependency_overrides[get_session] = _fake_session

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, session, fixed_workspace, tmp_path


def test_delete_ref_unlinks_local_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "R2_ENDPOINT", "")
    target = tmp_path / "raw.pdf"
    target.write_bytes(b"%PDF-1.4 minimal")

    # Step 1: the file is removed...
    delete_ref(str(target))
    assert not target.exists()

    # Step 2: ...and a second delete is a no-op, not an error (idempotent).
    delete_ref(str(target))


def test_delete_document_removes_raw_file(app_client: Any) -> None:
    client, session, workspace_id, tmp_path = app_client

    # Step 1: a stored upload that must not survive the delete.
    raw_file = tmp_path / "uploaded.pdf"
    raw_file.write_bytes(b"%PDF-1.4 minimal")

    doc = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        storage_path=str(raw_file),
        source_ref=str(raw_file),
        processing_status="done",
    )
    select_result = MagicMock()
    select_result.scalar_one_or_none = MagicMock(return_value=doc)
    # One select + four deletes (citations → chunks → job → document).
    session.execute = AsyncMock(
        side_effect=[select_result, MagicMock(), MagicMock(), MagicMock(), MagicMock()]
    )

    # Step 2: delete the document through the API...
    resp = client.delete(f"/api/ingestion/documents/{doc.id}")
    assert resp.status_code == 204

    # Step 3: ...and the raw upload is gone from disk too.
    assert not raw_file.exists()


def test_delete_document_missing_file_still_deletes_rows(app_client: Any) -> None:
    client, session, workspace_id, tmp_path = app_client

    # A storage_path pointing at a file that no longer exists must not fail
    # the endpoint — row cleanup already happened.
    doc = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        storage_path=str(tmp_path / "gone.pdf"),
        source_ref=str(tmp_path / "gone.pdf"),
        processing_status="done",
    )
    select_result = MagicMock()
    select_result.scalar_one_or_none = MagicMock(return_value=doc)
    session.execute = AsyncMock(
        side_effect=[select_result, MagicMock(), MagicMock(), MagicMock(), MagicMock()]
    )

    resp = client.delete(f"/api/ingestion/documents/{doc.id}")
    assert resp.status_code == 204
