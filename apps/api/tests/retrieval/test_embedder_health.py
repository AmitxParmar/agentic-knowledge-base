"""
Embedder readiness probe: health_check() status matrix + 60s cache behavior.

Mocks the Cohere client so no network calls happen.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.settings import settings
from src.retrieval import embedder


def _reset_cache() -> None:
    embedder._health_cache = None


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "COHERE_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ALLOW_EMBEDDING_FALLBACK", False)
    _reset_cache()
    yield
    _reset_cache()


async def test_health_check_ok() -> None:
    with patch.object(embedder, "embed_query", new=AsyncMock(return_value=[0.1])):
        assert await embedder.health_check() == "ok"


async def test_health_check_error_on_failure() -> None:
    with patch.object(
        embedder, "embed_query", new=AsyncMock(side_effect=RuntimeError("down"))
    ):
        status = await embedder.health_check()
    assert status == "error: RuntimeError"


async def test_health_check_unconfigured_without_key() -> None:
    monkey = pytest.MonkeyPatch()
    monkey.setattr(settings, "COHERE_API_KEY", "")
    try:
        assert await embedder.health_check() == "unconfigured"
    finally:
        monkey.undo()


async def test_health_check_skipped_in_dev_fallback() -> None:
    monkey = pytest.MonkeyPatch()
    monkey.setattr(settings, "COHERE_API_KEY", "")
    monkey.setattr(settings, "ALLOW_EMBEDDING_FALLBACK", True)
    try:
        assert await embedder.health_check() == "skipped (dev fallback)"
    finally:
        monkey.undo()


async def test_health_check_caches_success_for_ttl() -> None:
    calls = AsyncMock(return_value=[0.1])
    with patch.object(embedder, "embed_query", new=calls):
        assert await embedder.health_check() == "ok"
        assert await embedder.health_check() == "ok"
    # second probe within TTL must not re-hit the provider
    assert calls.await_count == 1


async def test_health_check_does_not_cache_failures() -> None:
    calls = AsyncMock(side_effect=RuntimeError("down"))
    with patch.object(embedder, "embed_query", new=calls):
        assert await embedder.health_check() == "error: RuntimeError"
        assert await embedder.health_check() == "error: RuntimeError"
    assert calls.await_count == 2


async def test_health_check_timeout_maps_to_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedder, "_PROBE_TIMEOUT_SECONDS", 0.05)

    async def hang() -> list[float]:
        await asyncio.sleep(1)
        return []

    with patch.object(embedder, "embed_query", new=hang):
        status = await embedder.health_check()
    assert status.startswith("error: ")