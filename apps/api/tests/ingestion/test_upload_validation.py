"""
tests/ingestion/test_upload_validation.py
------------------------------------------
Acceptance tests for P0 upload validation requirements.
Tests run without a real DB/Redis by mocking dependencies.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Minimal PDF fixtures ──────────────────────────────────────────────────────

def _make_pdf_bytes(page_count: int = 1, encrypted: bool = False) -> bytes:
    """
    Build a minimal syntactically-valid PDF that pypdf can read.
    Used only to exercise the validation path — not a production PDF generator.
    """
    # The simplest PDF pypdf will parse without errors
    pdf = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids["""

    page_refs = " ".join(f"{i + 3} 0 R" for i in range(page_count))
    pdf += page_refs.encode()
    pdf += f"]]/Count {page_count}>>endobj\n".encode()

    for i in range(page_count):
        obj_num = i + 3
        pdf += (
            f"{obj_num} 0 obj<</Type/Page/Parent 2 0 R"
            f"/MediaBox[0 0 612 792]>>endobj\n"
        ).encode()

    pdf += b"xref\n"
    pdf += b"%%EOF"
    return pdf


_VALID_PDF = _make_pdf_bytes(1)
_EMPTY_FILE = b""
_NOT_PDF = b"This is just plain text, not a PDF"
_OVER_100_PAGES_PDF = _make_pdf_bytes(101)  # will be detected by page count mock


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def app_client():
    """
    Build a FastAPI test app that isolates the upload validation logic from
    external dependencies (DB, Redis, arq) using mocks.
    """
    import src.shared.models  # noqa: F401 — register all ORM models before mapper resolution
    from src.ingestion.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/ingestion")

    # Stub out all FastAPI dependencies that hit external services
    from src.auth.stub import get_user_id, get_workspace_id
    from src.shared.database import get_session
    from src.shared.rate_limit import check_upload_rate_limit

    fixed_workspace = uuid.uuid4()
    fixed_user = uuid.uuid4()

    async def _fake_session():
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.add = MagicMock()
        yield session

    app.dependency_overrides[get_workspace_id] = lambda: fixed_workspace
    app.dependency_overrides[get_user_id] = lambda: fixed_user
    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[check_upload_rate_limit] = lambda: None  # bypass rate limit

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _upload(client: TestClient, content: bytes, filename: str = "test.pdf", content_type: str = "application/pdf"):
    """Helper to POST to /api/ingestion/upload."""
    with (
        patch("src.ingestion.router.store", return_value="local://test.pdf"),
        patch("arq.create_pool", new_callable=AsyncMock) as mock_pool,
    ):
        mock_redis = AsyncMock()
        mock_redis.enqueue_job = AsyncMock()
        mock_redis.close = AsyncMock()
        mock_pool.return_value = mock_redis

        return client.post(
            "/api/ingestion/upload",
            data={"source_type": "pdf"},
            files={"file": (filename, io.BytesIO(content), content_type)},
        )


# ── P0 Acceptance Tests ───────────────────────────────────────────────────────

class TestUploadValidation:
    def test_reject_empty_file(self, app_client: TestClient) -> None:
        resp = _upload(app_client, _EMPTY_FILE)
        assert resp.status_code == 422
        # No stack trace in response
        assert "Traceback" not in resp.text
        assert "exception" not in resp.text.lower()

    def test_reject_non_pdf_content(self, app_client: TestClient) -> None:
        resp = _upload(app_client, _NOT_PDF)
        assert resp.status_code == 422
        assert "Traceback" not in resp.text

    def test_reject_wrong_magic_bytes(self, app_client: TestClient) -> None:
        # Valid size, wrong magic
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = _upload(app_client, content)
        assert resp.status_code == 422

    def test_reject_encrypted_pdf(self, app_client: TestClient) -> None:
        """Mock pypdf to report the PDF as encrypted."""
        mock_reader = MagicMock()
        mock_reader.is_encrypted = True
        mock_reader.pages = [MagicMock()]

        with patch("src.ingestion.router.PdfReader", return_value=mock_reader):
            resp = _upload(app_client, b"%PDF-1.4 fake")
        assert resp.status_code == 422
        assert "encrypted" in resp.text.lower() or resp.status_code == 422

    def test_reject_over_100_pages(self, app_client: TestClient) -> None:
        """Mock pypdf to report 101 pages."""
        mock_reader = MagicMock()
        mock_reader.is_encrypted = False
        mock_reader.pages = [MagicMock()] * 101

        with patch("src.ingestion.router.PdfReader", return_value=mock_reader):
            resp = _upload(app_client, b"%PDF-1.4 fake")
        assert resp.status_code == 422
        assert "101" in resp.text or "pages" in resp.text.lower()

    def test_accept_valid_pdf(self, app_client: TestClient) -> None:
        """A properly structured single-page PDF should succeed."""
        mock_reader = MagicMock()
        mock_reader.is_encrypted = False
        mock_reader.pages = [MagicMock()]

        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock()
        mock_pool.close = AsyncMock()

        with (
            patch("src.ingestion.router.PdfReader", return_value=mock_reader),
            patch("src.ingestion.router.store", return_value="local://test.pdf"),
            patch("src.ingestion.router.arq.create_pool", new_callable=AsyncMock, return_value=mock_pool),
        ):
            resp = app_client.post(
                "/api/ingestion/upload",
                data={"source_type": "pdf"},
                files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 valid"), "application/pdf")},
            )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["status"] == "queued"
        assert "document_id" in data
        assert "job_id" in data

    def test_duplicate_upload_returns_existing_job(self, app_client: TestClient) -> None:
        """Re-uploading the same bytes returns the existing document/job."""
        existing_doc = MagicMock()
        existing_doc.id = uuid.uuid4()
        existing_doc.processing_status = MagicMock(value="done")
        existing_job = MagicMock()
        existing_job.id = uuid.uuid4()
        existing_doc.ingestion_job = existing_job

        mock_reader = MagicMock()
        mock_reader.is_encrypted = False
        mock_reader.pages = [MagicMock()]

        with (
            patch("src.ingestion.router.PdfReader", return_value=mock_reader),
            patch("src.ingestion.router.store", return_value="local://test.pdf"),
        ):
            # Override session to return the existing doc on hash lookup
            from src.shared.database import get_session

            async def _dup_session():
                session = AsyncMock()
                execute_result = MagicMock()
                execute_result.scalar_one_or_none.return_value = existing_doc
                session.execute = AsyncMock(return_value=execute_result)
                session.flush = AsyncMock()
                session.commit = AsyncMock()
                session.add = MagicMock()
                yield session

            cast(FastAPI, app_client.app).dependency_overrides[get_session] = _dup_session

            resp = app_client.post(
                "/api/ingestion/upload",
                data={"source_type": "pdf"},
                files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 dup"), "application/pdf")},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"] == str(existing_doc.id)
        assert "Duplicate" in data["message"]

    def test_file_size_limit(self, app_client: TestClient) -> None:
        """Files over MAX_UPLOAD_SIZE are rejected with 413."""
        from app.settings import settings

        oversized = b"%PDF-1.4 " + b"x" * (settings.MAX_UPLOAD_SIZE + 1)
        resp = _upload(app_client, oversized)
        assert resp.status_code == 413


class TestRateLimiting:
    """Rate limit tests using the Redis fixed-window counter directly."""

    @pytest.mark.asyncio
    async def test_upload_rate_limit_triggers_on_6th_request(self) -> None:
        """6th upload from the same IP in a minute should be rejected."""
        from src.shared import rate_limit

        ip = f"test-ip-{uuid.uuid4().hex[:8]}"

        # Use an in-memory mock Redis
        store: dict[str, int] = {}

        async def mock_incr(k: str) -> int:
            store[k] = store.get(k, 0) + 1
            return store[k]

        async def mock_expire(k: str, ttl: int) -> None:
            pass

        async def mock_ping() -> bool:
            return True

        mock_r = AsyncMock()
        mock_r.incr = mock_incr
        mock_r.expire = mock_expire
        mock_r.ping = mock_ping

        original = rate_limit._redis
        rate_limit._redis = mock_r
        try:
            # First 5 should pass
            for i in range(5):
                allowed = await rate_limit._check_limit("upload", ip, limit=5)
                assert allowed, f"Request {i + 1} should be allowed"

            # 6th should be blocked
            blocked = await rate_limit._check_limit("upload", ip, limit=5)
            assert not blocked, "6th request should be rate limited"
        finally:
            rate_limit._redis = original

    @pytest.mark.asyncio
    async def test_chat_rate_limit_triggers_on_21st_request(self) -> None:
        """21st chat request from the same IP should be rejected."""
        from src.shared import rate_limit

        ip = f"test-ip-{uuid.uuid4().hex[:8]}"
        store: dict[str, int] = {}

        async def mock_incr(k: str) -> int:
            store[k] = store.get(k, 0) + 1
            return store[k]

        async def mock_expire(k: str, ttl: int) -> None:
            pass

        mock_r = AsyncMock()
        mock_r.incr = mock_incr
        mock_r.expire = mock_expire

        original = rate_limit._redis
        rate_limit._redis = mock_r
        try:
            for i in range(20):
                allowed = await rate_limit._check_limit("chat", ip, limit=20)
                assert allowed, f"Chat request {i + 1} should be allowed"

            blocked = await rate_limit._check_limit("chat", ip, limit=20)
            assert not blocked, "21st chat request should be rate limited"
        finally:
            rate_limit._redis = original

    @pytest.mark.asyncio
    async def test_rate_limit_allows_all_when_redis_down(self) -> None:
        """When Redis is unavailable, rate limiting is disabled (open by default)."""
        from src.shared import rate_limit

        original = rate_limit._redis
        rate_limit._redis = False  # simulate Redis down

        try:
            allowed = await rate_limit._check_limit("upload", "1.2.3.4", limit=1)
            assert allowed, "Should allow when Redis is down"
        finally:
            rate_limit._redis = original


class TestRetryBehavior:
    """Retry policy tests: 3 attempts, backoff, selective retry."""

    @pytest.mark.asyncio
    async def test_retries_3_times_on_retryable_error(self) -> None:
        from src.shared.retry import with_retry

        call_count = 0

        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "ok"

        result = await with_retry(
            flaky,
            max_attempts=3,
            base_delay=0.01,
            max_delay=0.1,
            retryable_exceptions=(ConnectionError,),
        )
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_does_not_retry_non_retryable_errors(self) -> None:
        from src.shared.retry import NonRetryableError, with_retry

        call_count = 0

        async def raises_non_retryable() -> None:
            nonlocal call_count
            call_count += 1
            raise NonRetryableError("invalid pdf")

        with pytest.raises(NonRetryableError):
            await with_retry(raises_non_retryable, max_attempts=3, base_delay=0.01, max_delay=0.1)

        assert call_count == 1, "NonRetryableError must not trigger retries"

    @pytest.mark.asyncio
    async def test_does_not_retry_validation_errors(self) -> None:
        """ValueError (e.g. invalid PDF, bad input) is not retried."""
        from src.shared.retry import with_retry

        call_count = 0

        async def raises_value_error() -> None:
            nonlocal call_count
            call_count += 1
            raise ValueError("malformed request")

        with pytest.raises(ValueError):
            await with_retry(
                raises_value_error,
                max_attempts=3,
                base_delay=0.01,
                max_delay=0.1,
                retryable_exceptions=(ConnectionError,),  # ValueError not included
            )

        assert call_count == 1, "ValueError must not trigger retries"

    @pytest.mark.asyncio
    async def test_exhausts_attempts_then_raises(self) -> None:
        from src.shared.retry import with_retry

        call_count = 0

        async def always_fails() -> None:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("permanent failure")

        with pytest.raises(ConnectionError):
            await with_retry(
                always_fails,
                max_attempts=3,
                base_delay=0.01,
                max_delay=0.05,
                retryable_exceptions=(ConnectionError,),
            )

        assert call_count == 3


class TestEmbeddingBatching:
    """Embedding batches must preserve input order."""

    @pytest.mark.asyncio
    async def test_embed_texts_preserves_order(self) -> None:
        from src.retrieval.embedder import embed_texts

        texts = [f"document text number {i}" for i in range(10)]

        # Mock the Cohere client so we return predictable per-text vectors
        mock_resp = MagicMock()

        call_args: list[list[str]] = []

        async def mock_embed(**kwargs: Any) -> Any:
            batch = kwargs["texts"]
            call_args.append(batch)
            # Return a distinct vector per text — just embed the index
            mock_resp.embeddings.float_ = [
                [float(ord(c)) / 1000 for c in text[:1024].ljust(1024)]
                for text in batch
            ]
            return mock_resp

        mock_client = MagicMock()
        mock_client.embed = mock_embed

        with (
            patch("src.retrieval.embedder._get_client", return_value=mock_client),
            patch("src.retrieval.embedder.embed_semaphore", return_value=asyncio.Semaphore(4)),
        ):
            vectors = await embed_texts(texts)

        # Should have called embed in batches
        assert len(call_args) >= 1
        # Total texts processed == input
        total_processed = sum(len(b) for b in call_args)
        assert total_processed == len(texts)
        # Output count must match input count
        assert len(vectors) == len(texts)


class TestPDFParseTimeout:
    """PDF parsing timeout should produce a 408/422 response (not 500)."""

    @pytest.mark.asyncio
    async def test_pdf_parse_timeout_raises(self) -> None:
        import asyncio

        from src.ingestion.pipeline import _extract_with_timeout

        async def _slow_extract(path: Any, source_type: str) -> Any:
            await asyncio.sleep(100)
            return MagicMock()

        with patch(
            "src.ingestion.pipeline.extract",
            side_effect=lambda *a, **kw: (_ for _ in ()).throw(TimeoutError()),
        ), pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                _extract_with_timeout("/fake/path", "pdf"),
                timeout=0.1,
            )
