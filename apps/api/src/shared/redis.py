"""
shared/redis.py
---------------
Shared async Redis client singleton.

All feature modules that need Redis (rate limiting, semantic cache, etc.)
import from here instead of maintaining their own connections. One client
per process — created lazily on first use, closed on app shutdown.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from app.settings import settings

logger = logging.getLogger(__name__)

_redis: Any = None


async def redis_client() -> Any:
    """Return the shared async Redis client, creating it on first call.

    Returns ``None`` if Redis is unavailable — callers should treat this
    as "feature disabled" and fall back gracefully.
    """
    global _redis
    if _redis is not None:
        return _redis if _redis is not False else None
    try:
        import redis.asyncio as aioredis  # type: ignore[import-untyped]

        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception:
        logger.warning("redis: unavailable — dependent features disabled")
        _redis = False
        return None
    return _redis


async def close_redis() -> None:
    """Close the shared Redis connection. Called once on app shutdown."""
    global _redis
    if _redis and _redis is not False:
        with contextlib.suppress(Exception):
            await _redis.aclose()
        _redis = None
