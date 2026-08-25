"""
tests/retrieval/test_embed_query_cache.py
-----------------------------------------
The query-embedding LRU must serve repeats without a second provider call.
embed_texts is mocked — no Cohere, no network.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.retrieval import embedder


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    embedder._embed_query_cache.clear()
    yield  # type: ignore[misc]
    embedder._embed_query_cache.clear()


async def test_repeat_query_hits_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    monkeypatch.setattr(embedder, "embed_texts", mock_embed)

    first = await embedder.embed_query("what is quantum computing?")
    second = await embedder.embed_query("what is quantum computing?")

    assert first == [0.1, 0.2, 0.3]
    assert second == first
    assert mock_embed.await_count == 1


async def test_distinct_queries_each_call_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_embed = AsyncMock(side_effect=lambda texts, **kw: [[float(len(texts[0]))]])
    monkeypatch.setattr(embedder, "embed_texts", mock_embed)

    await embedder.embed_query("query one")
    await embedder.embed_query("query two")

    assert mock_embed.await_count == 2
    assert len(embedder._embed_query_cache) == 2


async def test_lru_evicts_oldest_beyond_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedder, "_EMBED_QUERY_CACHE_SIZE", 2)
    mock_embed = AsyncMock(side_effect=lambda texts, **kw: [[float(len(texts[0]))]])
    monkeypatch.setattr(embedder, "embed_texts", mock_embed)

    await embedder.embed_query("a")
    await embedder.embed_query("b")
    await embedder.embed_query("c")  # evicts "a"

    assert set(embedder._embed_query_cache) == {"b", "c"}

    # Re-querying "a" must miss → provider called again.
    await embedder.embed_query("a")
    assert mock_embed.await_count == 4  # a, b, c, a-miss
