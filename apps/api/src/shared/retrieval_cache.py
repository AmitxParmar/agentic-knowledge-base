"""
shared/retrieval_cache.py
-------------------------
Redis TTL cache of retrieval results per (workspace, question).

The agent loop may issue the same or near-identical queries across turns,
and repeat questions re-run the full HyDE + hybrid + rerank pipeline.
Caching the final selected chunks short-circuits that for a few minutes.

Storage layout (Redis, all keys TTL'd at RETRIEVAL_CACHE_TTL):
  rcache:{ws}:{query_hash}   → STRING (JSON chunk dicts)   TTL
  rcache:idx:{ws}            → SET of query hashes         TTL

Graceful degradation mirrors the semantic cache (ADR-007 pattern): every
operation is best-effort; any Redis failure is a cache miss. Entries are
evicted whenever the workspace corpus changes — an answer is only valid
for the corpus that produced it — via ``invalidate_retrieval_cache``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import logfire

from app.settings import settings
from src.shared.redis import redis_client

logger = logging.getLogger(__name__)


def _normalize(question: str) -> str:
    return " ".join(question.strip().lower().split())


def _query_hash(question: str) -> str:
    return hashlib.sha256(_normalize(question).encode()).hexdigest()[:16]


def _key_entry(ws: str, qhash: str) -> str:
    return f"rcache:{ws}:{qhash}"


def _key_index(ws: str) -> str:
    return f"rcache:idx:{ws}"


async def get_cached_chunks(workspace_id: str, question: str) -> list[dict[str, Any]] | None:
    """Return cached chunk dicts for this exact question, or None on miss."""
    if not settings.RETRIEVAL_CACHE_ENABLED:
        return None
    r = await redis_client()
    if not r:
        return None
    try:
        ws = str(workspace_id)
        raw = await r.get(_key_entry(ws, _query_hash(question)))
        if raw is None:
            return None
        chunks = json.loads(raw)
        logfire.info("retrieval_cache.hit", workspace_id=ws, chunks=len(chunks))
        return chunks
    except Exception:
        logger.debug("retrieval_cache: get failed", exc_info=True)
        return None


async def store_chunks(
    workspace_id: str,
    question: str,
    chunks: list[dict[str, Any]],
) -> None:
    """Persist selected chunks as JSON. Best-effort; never raises."""
    if not settings.RETRIEVAL_CACHE_ENABLED or not chunks:
        return
    r = await redis_client()
    if not r:
        return
    try:
        ws = str(workspace_id)
        qhash = _query_hash(question)
        ttl = settings.RETRIEVAL_CACHE_TTL
        pipe = r.pipeline()
        pipe.set(_key_entry(ws, qhash), json.dumps(chunks), ex=ttl)
        pipe.sadd(_key_index(ws), qhash)
        pipe.expire(_key_index(ws), ttl)
        await pipe.execute()
        logfire.info("retrieval_cache.stored", workspace_id=ws, chunks=len(chunks))
    except Exception:
        logger.debug("retrieval_cache: store failed", exc_info=True)


async def invalidate_retrieval_cache(workspace_id: str) -> int:
    """Evict every cached retrieval result for a workspace. Never raises."""
    r = await redis_client()
    if not r:
        return 0
    try:
        ws = str(workspace_id)
        qhashes = list(await r.smembers(_key_index(ws)))
        if not qhashes:
            return 0
        pipe = r.pipeline()
        for qh in qhashes:
            pipe.delete(_key_entry(ws, qh))
        pipe.delete(_key_index(ws))
        await pipe.execute()
        logfire.info("retrieval_cache.invalidated", workspace_id=ws, entries=len(qhashes))
        return len(qhashes)
    except Exception:
        logger.debug("retrieval_cache: invalidation failed", exc_info=True)
        return 0
