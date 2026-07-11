from __future__ import annotations

import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import create_app
from src.ingestion.models import JobStage
from src.shared.database import get_session


class FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeSession:
    def __init__(self) -> None:
        self.document = None
        self.job = None
        self.flush_calls = 0
        self.commit_calls = 0

    def add(self, obj) -> None:
        name = obj.__class__.__name__
        if name == "Document":
            self.document = obj
        elif name == "IngestionJob":
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            self.job = obj

    async def flush(self) -> None:
        self.flush_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1

    async def execute(self, stmt):
        params = getattr(getattr(stmt, "compile", lambda: None)(), "params", {})
        job_id = params.get("id_1")
        if self.job is not None and job_id == self.job.id:
            return FakeScalarResult(self.job)
        return FakeScalarResult(None)


async def override_session():
    yield fake_session


fake_session = FakeSession()


def test_upload_document_queues_background_job() -> None:
    app = create_app()
    app.dependency_overrides[get_session] = override_session

    pool = SimpleNamespace(enqueue_job=AsyncMock(), close=AsyncMock())

    with patch("src.ingestion.router.arq.create_pool", new=AsyncMock(return_value=pool)):
        client = TestClient(app)
        response = client.post(
            "/api/ingestion/upload",
            files={"file": ("sample.pdf", io.BytesIO(b"pdf-bytes"), "application/pdf")},
            data={"source_type": "pdf"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert fake_session.document is not None
    assert fake_session.job is not None
    assert fake_session.job.stage == JobStage.queued
    assert JobStage.queued.value in fake_session.job.stage_timestamps
    pool.enqueue_job.assert_awaited_once()
    pool.close.assert_awaited_once()
    app.dependency_overrides.clear()
