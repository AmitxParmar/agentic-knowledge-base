"""
Tests for the semantic answer cache (ADR-007).

Redis and the Cohere embedder are mocked — no external services. A tiny
in-memory FakeRedis stands in for the async client so lookup/store round-trip
without touching a real server.
"""

import json

import pytest

from app.settings import settings
from src.shared.semantic_cache import (
    SemanticCache,
    _cosine_similarity,
    _key_entry,
    _key_exact,
    _key_index,
    _normalize_query,
    _pack_embedding,
    _query_hash,
)

# ── Fake Redis ────────────────────────────────────────────────────────────────


class _FakePipe:
    """Pipeline stub that applies ops to the fake store on execute()."""

    def __init__(self, redis: "FakeRedis") -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple]] = []

    def hgetall(self, key: str) -> "_FakePipe":
        self._ops.append(("hgetall", (key,)))
        return self

    def hget(self, key: str, field: str) -> "_FakePipe":
        self._ops.append(("hget", (key, field)))
        return self

    def set(self, key: str, value: str, **kwargs: object) -> "_FakePipe":
        self._ops.append(("set", (key, value)))
        return self

    def hset(self, key: str, mapping: dict[str, str], **kwargs: object) -> "_FakePipe":
        self._ops.append(("hset", (key, mapping)))
        return self

    def sadd(self, key: str, *members: str) -> "_FakePipe":
        self._ops.append(("sadd", (key, members)))
        return self

    def delete(self, *keys: str) -> "_FakePipe":
        self._ops.append(("delete", keys))
        return self

    def expire(self, key: str, ttl: int) -> "_FakePipe":
        self._ops.append(("expire", (key, ttl)))
        return self

    async def execute(self) -> list[object]:
        results: list[object] = []
        for op, args in self._ops:
            if op == "hgetall":
                results.append(self._redis._entries.get(args[0], {}))
            elif op == "hget":
                results.append(self._redis._entries.get(args[0], {}).get(args[1]))
            elif op == "set":
                self._redis._exact[args[0]] = args[1]
                results.append(True)
            elif op == "hset":
                self._redis._entries[args[0]] = args[1]
                results.append(1)
            elif op == "sadd":
                self._redis._index.setdefault(args[0], set()).update(args[1])
                results.append(1)
            elif op == "delete":
                results.append(await self._redis.delete(*args))
            elif op == "expire":
                results.append(True)
        return results


class FakeRedis:
    """In-memory stand-in for the redis.asyncio client."""

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, str]] = {}
        self._index: dict[str, set[str]] = {}
        self._exact: dict[str, str] = {}
        self._metrics: dict[str, dict[str, int]] = {}

    async def get(self, key: str) -> str | None:
        return self._exact.get(key)

    async def hgetall(self, key: str) -> dict[str, str]:
        if key.startswith("scache:m:"):
            return {k: str(v) for k, v in self._metrics.get(key, {}).items()}
        return self._entries.get(key, {})

    async def smembers(self, key: str) -> set[str]:
        return set(self._index.get(key, set()))

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if self._entries.pop(key, None) is not None:
                removed += 1
            if self._exact.pop(key, None) is not None:
                removed += 1
            if self._metrics.pop(key, None) is not None:
                removed += 1
            if self._index.pop(key, None) is not None:
                removed += 1
        return removed

    async def hincrby(self, key: str, field: str, amount: int = 1) -> int:
        entry = self._metrics.setdefault(key, {})
        entry[field] = entry.get(field, 0) + amount
        return entry[field]

    async def expire(self, key: str, ttl: int) -> bool:
        return True

    def pipeline(self) -> _FakePipe:
        return _FakePipe(self)


def make_entry(answer: str, vector: list[float], ws: str, citations: list[dict] | None = None) -> dict[str, str]:
    return {
        "q": "seed question",
        "a": answer,
        "cites": json.dumps(citations or []),
        "conf": "sufficient",
        "emb": _pack_embedding(vector).decode("latin-1"),
        "ts": "2026-08-18T00:00:00+00:00",
        "ws": ws,
    }


# ── Unit: pure helpers ───────────────────────────────────────────────────────


def test_normalize_query_collapses_whitespace_and_case() -> None:
    assert _normalize_query("  What   IS\n Quantum?  ") == "what is quantum?"


def test_query_hash_is_deterministic_per_normal_form() -> None:
    assert _query_hash(" What is X? ") == _query_hash("what is x?")


def test_cosine_identical_vectors() -> None:
    assert _cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0


def test_cosine_orthogonal_vectors() -> None:
    assert abs(_cosine_similarity([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])) < 1e-9


def test_cosine_mismatched_lengths_is_zero() -> None:
    assert _cosine_similarity([1.0], [1.0, 2.0]) == 0.0


# ── Lookup ────────────────────────────────────────────────────────────────────


async def test_exact_hash_hit_skips_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = "ws-a"
    question = "What is quantum computing?"
    fake = FakeRedis()
    entry_id = "e123"
    fake._exact[_key_exact(ws, _query_hash(question))] = entry_id
    fake._entries[_key_entry(entry_id)] = make_entry(
        "Cached answer", [1.0, 0.0, 0.0], ws,
        citations=[{"chunk_id": "c1", "source_ref": "s1", "relevance_score": 0.9}],
    )
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_ENABLED", True)
    monkeypatch.setattr("src.shared.semantic_cache.redis_client", _async_redis(fake))

    async def boom(*args: object, **kwargs: object) -> list[float]:
        raise AssertionError("embed_query must not be called on an exact hash hit")

    monkeypatch.setattr("src.retrieval.embedder.embed_query", boom)

    hit = await SemanticCache().lookup(ws, question)
    assert hit is not None
    assert hit.answer == "Cached answer"
    assert hit.similarity == 1.0
    assert hit.citations[0]["chunk_id"] == "c1"


async def test_semantic_hit_above_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = "ws-a"
    fake = FakeRedis()
    entry_id = "e1"
    fake._index.setdefault(_key_index(ws), set()).add(entry_id)
    fake._entries[_key_entry(entry_id)] = make_entry("Cached answer", [1.0, 0.0, 0.0], ws)
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_ENABLED", True)
    monkeypatch.setattr("src.shared.semantic_cache.redis_client", _async_redis(fake))

    async def embed(query: str) -> list[float]:
        return [0.95, 0.05, 0.0]

    monkeypatch.setattr("src.retrieval.embedder.embed_query", embed)

    hit = await SemanticCache().lookup(ws, "Tell me about quantum computing")
    assert hit is not None
    assert hit.answer == "Cached answer"
    assert hit.similarity >= 0.85


async def test_semantic_miss_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = "ws-a"
    fake = FakeRedis()
    entry_id = "e1"
    fake._index.setdefault(_key_index(ws), set()).add(entry_id)
    fake._entries[_key_entry(entry_id)] = make_entry("Cached answer", [1.0, 0.0, 0.0], ws)
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_ENABLED", True)
    monkeypatch.setattr("src.shared.semantic_cache.redis_client", _async_redis(fake))

    async def embed(query: str) -> list[float]:
        return [0.5, 0.5, 0.0]

    monkeypatch.setattr("src.retrieval.embedder.embed_query", embed)

    hit = await SemanticCache().lookup(ws, "Unrelated question")
    assert hit is None


async def test_workspace_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    fake._index.setdefault(_key_index("ws-a"), set()).add("e1")
    fake._entries[_key_entry("e1")] = make_entry("Cached answer", [1.0, 0.0, 0.0], "ws-a")
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_ENABLED", True)
    monkeypatch.setattr("src.shared.semantic_cache.redis_client", _async_redis(fake))

    async def embed(query: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr("src.retrieval.embedder.embed_query", embed)

    assert await SemanticCache().lookup("ws-b", "What is quantum computing?") is None


async def test_redis_unavailable_returns_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_redis() -> None:
        return None

    monkeypatch.setattr(settings, "SEMANTIC_CACHE_ENABLED", True)
    monkeypatch.setattr("src.shared.semantic_cache.redis_client", no_redis)

    hit = await SemanticCache().lookup("ws-a", "What is quantum computing?")
    assert hit is None


async def test_disabled_flag_never_touches_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def no_redis() -> None:
        calls.append("redis_client")
        return None

    monkeypatch.setattr(settings, "SEMANTIC_CACHE_ENABLED", False)
    monkeypatch.setattr("src.shared.semantic_cache.redis_client", no_redis)

    hit = await SemanticCache().lookup("ws-a", "question")
    assert hit is None
    assert calls == [], "disabled cache must not touch Redis"


# ── Store ─────────────────────────────────────────────────────────────────────


async def test_store_then_lookup_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_ENABLED", True)
    monkeypatch.setattr("src.shared.semantic_cache.redis_client", _async_redis(fake))

    vectors = {
        "What is quantum computing?": [1.0, 0.0, 0.0],
        "Tell me about quantum computing": [0.95, 0.05, 0.0],
    }

    async def embed(query: str) -> list[float]:
        return vectors[query]

    monkeypatch.setattr("src.retrieval.embedder.embed_query", embed)

    cache = SemanticCache()
    await cache.store(
        "ws-a", "What is quantum computing?", "The answer.",
        [{"chunk_id": "c1", "source_ref": "s1"}], "sufficient",
    )

    exact = await cache.lookup("ws-a", "what is   QUANTUM computing?")
    assert exact is not None
    assert exact.answer == "The answer."
    assert exact.similarity == 1.0

    semantic = await cache.lookup("ws-a", "Tell me about quantum computing")
    assert semantic is not None
    assert semantic.answer == "The answer."
    assert semantic.citations[0]["chunk_id"] == "c1"


def _async_redis(fake: FakeRedis):
    async def client() -> FakeRedis:
        return fake

    return client


# ── Invalidation ──────────────────────────────────────────────────────────────


async def _seed_two_entries(fake: FakeRedis, monkeypatch: pytest.MonkeyPatch) -> SemanticCache:
    """Store two answers in ws-a and return the cache instance."""
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_ENABLED", True)
    monkeypatch.setattr("src.shared.semantic_cache.redis_client", _async_redis(fake))

    async def embed(query: str) -> list[float]:
        vectors = {
            "What is quantum computing?": [1.0, 0.0, 0.0],
            "What is machine learning?": [0.0, 1.0, 0.0],
        }
        # Unknown queries land between both entries: cosine ≈ 0.71 < threshold.
        return vectors.get(query, [0.5, 0.5, 0.0])

    monkeypatch.setattr("src.retrieval.embedder.embed_query", embed)

    cache = SemanticCache()
    await cache.store("ws-a", "What is quantum computing?", "Answer A.", [])
    await cache.store("ws-a", "What is machine learning?", "Answer B.", [])
    return cache


async def test_invalidate_workspace_evicts_all_tiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    cache = await _seed_two_entries(fake, monkeypatch)

    # Both tiers resolve before invalidation.
    assert await cache.lookup("ws-a", "What is quantum computing?") is not None

    removed = await cache.invalidate_workspace("ws-a")
    assert removed == 2
    assert fake._index.get(_key_index("ws-a")) is None
    assert fake._entries == {}
    assert fake._exact == {}

    # Every tier misses afterwards.
    assert await cache.lookup("ws-a", "What is quantum computing?") is None


async def test_invalidate_workspace_empty_index_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_ENABLED", True)
    monkeypatch.setattr("src.shared.semantic_cache.redis_client", _async_redis(FakeRedis()))

    assert await SemanticCache().invalidate_workspace("ws-empty") == 0


async def test_invalidation_does_not_touch_other_workspaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    cache = await _seed_two_entries(fake, monkeypatch)

    assert await cache.invalidate_workspace("ws-b") == 0
    hit = await cache.lookup("ws-a", "What is quantum computing?")
    assert hit is not None
    assert hit.answer == "Answer A."


# ── Metrics ───────────────────────────────────────────────────────────────────


async def test_metrics_count_hits_misses_and_stores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    cache = await _seed_two_entries(fake, monkeypatch)

    await cache.lookup("ws-a", "What is quantum computing?")  # exact hit
    await cache.lookup("ws-a", "Tell me about quantum computing")  # below threshold

    stats = await cache.stats("ws-a")
    assert stats["stores"] == 2
    assert stats["hits_exact"] == 1
    assert stats["misses"] >= 1
    assert stats["lookups"] == stats["hits_exact"] + stats["hits_semantic"] + stats["misses"]


async def test_stats_without_redis_returns_zeros(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_redis() -> None:
        return None

    monkeypatch.setattr("src.shared.semantic_cache.redis_client", no_redis)

    stats = await SemanticCache().stats("ws-a")
    assert stats["hits_exact"] == 0
    assert stats["misses"] == 0
    assert stats["lookups"] == 0