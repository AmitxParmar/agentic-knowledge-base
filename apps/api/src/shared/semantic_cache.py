"""
shared/semantic_cache.py
-------------------------
Semantic answer cache backed by Redis + Cohere embeddings.

Caches completed research answers keyed by the semantic similarity of the
query. When a new question's embedding has cosine similarity ≥ threshold
to a cached entry (within the same workspace), the cached answer is
returned directly — skipping the full retrieval + LLM pipeline.

Lookup strategy (two-tier):
  1. Exact hash — normalized question → SHA-256 → Redis GET. Free hit
     without any embedding call.
  2. Semantic scan — embed the query, fetch workspace entries, cosine
     compare, return best match if ≥ threshold.

Storage layout (Redis):
  scache:eq:{workspace_id}:{query_hash}  → STRING (entry_id)     TTL
  scache:e:{entry_id}                    → HASH (fields below)   TTL
  scache:idx:{workspace_id}              → SET of entry_ids      TTL

Hash fields per entry: q, a, cites (JSON), conf, emb (binary), ts.

Graceful degradation: every Redis operation is wrapped in try/except.
On failure the lookup returns None (cache miss) and the caller proceeds
with the normal pipeline. No crash, no partial state.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import struct
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import logfire

from app.settings import settings
from src.shared.redis import redis_client

logger = logging.getLogger(__name__)


# ── Public types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CacheHit:
    """A cached answer ready to return to the client."""

    answer: str
    citations: list[dict[str, Any]]
    confidence: Literal["sufficient", "insufficient"]
    similarity: float
    entry_id: str


# ── Internal helpers ──────────────────────────────────────────────────────────


def _normalize_query(question: str) -> str:
    """Strip, collapse whitespace, lowercase — the normal form for hashing."""
    return " ".join(question.strip().lower().split())


def _query_hash(question: str) -> str:
    """SHA-256 of the normalized question."""
    return hashlib.sha256(_normalize_query(question).encode()).hexdigest()[:16]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length float vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _pack_embedding(vector: list[float]) -> bytes:
    """Pack a float vector into binary (little-endian float32)."""
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack_embedding(data: bytes) -> list[float]:
    """Unpack binary float32 data into a list of floats."""
    count = len(data) // 4
    return list(struct.unpack(f"<{count}f", data))


def _key_exact(workspace_id: str, qhash: str) -> str:
    return f"scache:eq:{workspace_id}:{qhash}"


def _key_entry(entry_id: str) -> str:
    return f"scache:e:{entry_id}"


def _key_index(workspace_id: str) -> str:
    return f"scache:idx:{workspace_id}"


# ── Semantic cache ─────────────────────────────────────────────────────────────


class SemanticCache:
    """Two-tier semantic answer cache using Redis + Cohere embeddings.

    Usage::

        cache = SemanticCache()
        hit = await cache.lookup(workspace_id, question)
        if hit:
            return hit.answer, hit.citations

        # ... run full pipeline ...
        await cache.store(workspace_id, question, answer, citations, confidence, embedding)
    """

    def __init__(self) -> None:
        self._enabled = settings.SEMANTIC_CACHE_ENABLED
        self._ttl = settings.SEMANTIC_CACHE_TTL
        self._threshold = settings.SEMANTIC_CACHE_THRESHOLD

    async def lookup(
        self,
        workspace_id: str,
        question: str,
    ) -> CacheHit | None:
        """Check the cache for a semantically similar question.

        Returns a CacheHit on match, or None on miss. Never raises —
        Redis or embedding failures silently degrade to a cache miss.
        """
        if not self._enabled:
            return None

        r = await redis_client()
        if not r:
            return None

        ws = str(workspace_id)

        with logfire.span("semantic_cache.lookup", workspace_id=ws):
            # ── Tier 1: exact hash (no embedding call) ────────────────
            try:
                qhash = _query_hash(question)
                entry_id = await r.get(_key_exact(ws, qhash))
                if entry_id:
                    entry = await r.hgetall(_key_entry(entry_id))
                    if entry and entry.get("a"):
                        logfire.info("semantic_cache.hit", tier="exact", entry_id=entry_id)
                        return CacheHit(
                            answer=entry["a"],
                            citations=json.loads(entry.get("cites", "[]")),
                            confidence=entry.get("conf", "sufficient"),
                            similarity=1.0,
                            entry_id=entry_id,
                        )
            except Exception:
                logger.debug("semantic_cache: exact-lookup failed", exc_info=True)

            # ── Tier 2: semantic scan (embedding + cosine) ──────────────
            try:
                from src.retrieval.embedder import embed_query

                query_embedding = await embed_query(question)

                entry_ids = list(await r.smembers(_key_index(ws)))
                if not entry_ids:
                    return None

                # Batch-fetch all entries in a pipeline for efficiency.
                pipe = r.pipeline()
                for eid in entry_ids:
                    pipe.hgetall(_key_entry(eid))
                entries = await pipe.execute()

                best_sim = 0.0
                best_entry: dict[str, str] | None = None
                best_eid: str | None = None

                for eid, entry in zip(entry_ids, entries, strict=True):
                    if not entry or "emb" not in entry:
                        continue
                    try:
                        # emb was stored latin-1-decoded; encode back with the
                        # same codec or the binary round-trip corrupts the vector.
                        cached_emb = _unpack_embedding(entry["emb"].encode("latin-1"))
                        sim = _cosine_similarity(query_embedding, cached_emb)
                        if sim > best_sim:
                            best_sim = sim
                            best_entry = entry
                            best_eid = eid
                    except Exception:
                        continue

                if best_sim >= self._threshold and best_entry and best_eid:
                    logfire.info(
                        "semantic_cache.hit",
                        tier="semantic",
                        similarity=round(best_sim, 4),
                        entry_id=best_eid,
                    )
                    return CacheHit(
                        answer=best_entry["a"],
                        citations=json.loads(best_entry.get("cites", "[]")),
                        confidence=(
                            "insufficient"
                            if best_entry.get("conf", "sufficient") == "insufficient"
                            else "sufficient"
                        ),
                        similarity=round(best_sim, 4),
                        entry_id=best_eid,
                    )

                logfire.info("semantic_cache.miss", best_similarity=round(best_sim, 4))
                return None

            except Exception:
                logger.debug("semantic_cache: semantic-lookup failed", exc_info=True)
                return None

    async def store(
        self,
        workspace_id: str,
        question: str,
        answer: str,
        citations: list[dict[str, Any]],
        confidence: Literal["sufficient", "insufficient"] = "sufficient",
    ) -> None:
        """Persist a completed answer in the cache.

        Called after a successful run_agent() invocation. Embeds the question
        with the same ``embed_query`` call the lookup path uses, so stored
        vectors and lookup vectors live in the same space. Never raises —
        Redis or embedding failures are silently ignored (the cache is an
        optimization, never a dependency).
        """
        if not self._enabled:
            return

        r = await redis_client()
        if not r:
            return

        ws = str(workspace_id)
        entry_id = uuid.uuid4().hex[:12]
        qhash = _query_hash(question)
        now = datetime.now(UTC).isoformat()

        with logfire.span("semantic_cache.store", workspace_id=ws, entry_id=entry_id):
            try:
                # Same lazy import + embedding mode as the lookup path —
                # consistency here is what makes cosine comparison valid.
                from src.retrieval.embedder import embed_query

                query_embedding = await embed_query(question)

                pipe = r.pipeline()

                # Exact-match index: normalized hash → entry_id
                pipe.set(_key_exact(ws, qhash), entry_id, ex=self._ttl)

                # Entry data
                pipe.hset(
                    _key_entry(entry_id),
                    mapping={
                        "q": question,
                        "a": answer,
                        "cites": json.dumps(citations),
                        "conf": confidence,
                        "emb": _pack_embedding(query_embedding).decode("latin-1"),
                        "ts": now,
                        "ws": ws,
                    },
                )
                pipe.expire(_key_entry(entry_id), self._ttl)

                # Workspace index
                pipe.sadd(_key_index(ws), entry_id)
                pipe.expire(_key_index(ws), self._ttl)

                await pipe.execute()
                logfire.info("semantic_cache.stored", entry_id=entry_id)

            except Exception:
                logger.debug("semantic_cache: store failed", exc_info=True)
