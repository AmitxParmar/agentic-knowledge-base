"""
tests/shared/test_retrieval_cache.py
------------------------------------
Retrieval-cache behavior with an in-memory fake Redis (no services):
round-trip, workspace isolation, invalidation, flag-off, Redis-down.
"""

from __future__ import annotations

import json

import pytest

from app.settings import settings
from src.shared import retrieval_cache as rc


class FakeRedis:
    def __init__(self) -> None:
        self.strings: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)

    async def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    def pipeline(self) -> FakePipe:
        return FakePipe(self)


class FakePipe:
    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple]] = []

    def set(self, key: str, value: str, **kwargs: object) -> FakePipe:
        self._ops.append(("set", (key, value)))
        return self

    def sadd(self, key: str, *members: str) -> FakePipe:
        self._ops.append(("sadd", (key, members)))
        return self

    def delete(self, *keys: str) -> FakePipe:
        self._ops.append(("delete", keys))
        return self

    def expire(self, key: str, ttl: int) -> FakePipe:
        return self

    async def execute(self) -> list[object]:
        for op, args in self._ops:
            if op == "set":
                self._redis.strings[args[0]] = args[1]
            elif op == "sadd":
                self._redis.sets.setdefault(args[0], set()).update(args[1])
            elif op == "delete":
                for key in args:
                    self._redis.strings.pop(key, None)
                    self._redis.sets.pop(key, None)
        return [True] * len(self._ops)


def _chunks() -> list[dict]:
    return [
        {
            "chunk_id": "c1",
            "document_id": "d1",
            "chunk_text": "text one",
            "source_ref": "a.pdf, chunk 1",
            "relevance_score": 0.9,
            "position": 1,
        }
    ]


@pytest.fixture(autouse=True)
def _enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "RETRIEVAL_CACHE_ENABLED", True)


def _patch(fake: FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
    async def client() -> FakeRedis:
        return fake

    monkeypatch.setattr(rc, "redis_client", client)


async def test_store_then_get_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    _patch(fake, monkeypatch)

    await rc.store_chunks("ws-a", "what is the refund policy?", _chunks())
    hit = await rc.get_cached_chunks("ws-a", "  What is the REFUND   policy? ")  # normalized
    assert hit is not None
    assert hit == _chunks()
    assert json.loads(fake.strings["rcache:ws-a:" + rc._query_hash("what is the refund policy?")])


async def test_miss_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(FakeRedis(), monkeypatch)
    assert await rc.get_cached_chunks("ws-a", "unknown question") is None


async def test_workspace_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    _patch(fake, monkeypatch)
    await rc.store_chunks("ws-a", "question", _chunks())
    assert await rc.get_cached_chunks("ws-b", "question") is None


async def test_invalidate_evicts_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    _patch(fake, monkeypatch)
    await rc.store_chunks("ws-a", "q1", _chunks())
    await rc.store_chunks("ws-a", "q2", _chunks())

    removed = await rc.invalidate_retrieval_cache("ws-a")

    assert removed == 2
    assert await rc.get_cached_chunks("ws-a", "q1") is None
    assert await rc.get_cached_chunks("ws-a", "q2") is None
    assert fake.strings == {}


async def test_disabled_flag_never_touches_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "RETRIEVAL_CACHE_ENABLED", False)
    calls: list[str] = []

    async def client() -> FakeRedis:
        calls.append("hit")
        return FakeRedis()

    monkeypatch.setattr(rc, "redis_client", client)

    assert await rc.get_cached_chunks("ws-a", "q") is None
    await rc.store_chunks("ws-a", "q", _chunks())
    assert calls == []


async def test_redis_down_degrades_to_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_redis() -> None:
        return None

    monkeypatch.setattr(rc, "redis_client", no_redis)
    assert await rc.get_cached_chunks("ws-a", "q") is None
    await rc.store_chunks("ws-a", "q", _chunks())  # must not raise
    assert await rc.invalidate_retrieval_cache("ws-a") == 0
