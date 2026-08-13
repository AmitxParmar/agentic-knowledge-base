"""
shared/rate_limit.py
--------------------
Rate limiting via Redis fixed-window counters.
Policy: INCR rl:{route}:{ip}:{minute} / EXPIRE 60
Concurrency semaphores: module-level, lazily created.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from fastapi import HTTPException, Request

from app.settings import settings

logger = logging.getLogger(__name__)

# ── Redis client (lazy singleton) ─────────────────────────────────────────────

_redis: Any = None


async def _get_redis() -> Any:
    global _redis
    if _redis is not None:
        return _redis
    try:
        import redis.asyncio as aioredis  # type: ignore[import-untyped]

        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception:
        logger.warning("rate_limit: Redis unavailable — rate limiting disabled")
        _redis = False
    return _redis


async def close_redis() -> None:
    """Close the Redis connection on shutdown."""
    global _redis
    if _redis and _redis is not False:
        with contextlib.suppress(Exception):
            await _redis.aclose()
        _redis = None


# ── Fixed-window counter ──────────────────────────────────────────────────────


async def _check_limit(route: str, ip: str, limit: int) -> bool:
    """
    Returns True (allowed) or False (rate limited).
    Key: rl:{route}:{ip}:{minute_bucket}
    Falls back to allow-all if Redis is unavailable.
    """
    r = await _get_redis()
    if not r:
        return True  # Redis down → open

    minute = int(time.time()) // 60
    key = f"rl:{route}:{ip}:{minute}"
    try:
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, 60)
        return count <= limit
    except Exception:
        logger.warning("rate_limit: Redis error — allowing request")
        return True


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def check_upload_rate_limit(request: Request) -> None:
    """Dependency: raises 429 if upload rate limit exceeded."""
    ip = get_client_ip(request)
    if not await _check_limit("upload", ip, settings.UPLOAD_RATE_LIMIT):
        raise HTTPException(
            status_code=429,
            detail="Too many uploads. Please wait before trying again.",
            headers={"Retry-After": "60"},
        )


async def check_chat_rate_limit(request: Request) -> None:
    """Dependency: raises 429 if chat rate limit exceeded."""
    ip = get_client_ip(request)
    if not await _check_limit("chat", ip, settings.CHAT_RATE_LIMIT):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait before trying again.",
            headers={"Retry-After": "60"},
        )


# ── Concurrency semaphores ────────────────────────────────────────────────────
# Module-level; lazily initialized on first use (avoids event-loop binding issues
# that arise when objects are created at import time in test environments).

_pdf_parse_sem: asyncio.Semaphore | None = None
_indexing_sem: asyncio.Semaphore | None = None
_embed_sem: asyncio.Semaphore | None = None


def pdf_parse_semaphore() -> asyncio.Semaphore:
    global _pdf_parse_sem
    if _pdf_parse_sem is None:
        _pdf_parse_sem = asyncio.Semaphore(settings.MAX_CONCURRENT_PDF_PARSES)
    return _pdf_parse_sem


def indexing_semaphore() -> asyncio.Semaphore:
    global _indexing_sem
    if _indexing_sem is None:
        _indexing_sem = asyncio.Semaphore(settings.MAX_CONCURRENT_INDEXING)
    return _indexing_sem


def embed_semaphore() -> asyncio.Semaphore:
    global _embed_sem
    if _embed_sem is None:
        _embed_sem = asyncio.Semaphore(4)  # 4 concurrent embedding requests
    return _embed_sem