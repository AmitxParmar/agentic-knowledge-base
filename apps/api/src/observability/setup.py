"""
observability/setup.py
----------------------
Purpose:    Boot Logfire (structured traces + metrics) and Langfuse (agent run tracing, N3).
            Call configure() once at app startup — idempotent after first call.
Dependencies: settings, logfire, langfuse
Scope:      Wiring only. Actual span/trace calls live in each feature module.

Usage:
    from apps.api.src.observability.setup import configure, get_langfuse
    configure()           # in lifespan
    lf = get_langfuse()   # in agent/retrieval code
"""

from __future__ import annotations

import logging
from functools import lru_cache

import logfire
from langfuse import Langfuse

from apps.api.app.settings import settings

logger = logging.getLogger(__name__)

_configured = False


def configure() -> None:
    """
    Wire up Logfire and validate Langfuse credentials.
    Safe to call multiple times — only runs once.
    """
    global _configured
    if _configured:
        return

    # ── Logfire ───────────────────────────────────────────────────────────
    if settings.LOGFIRE_TOKEN:
        logfire.configure(token=settings.LOGFIRE_TOKEN)
    else:
        # Dev mode: log to console, no remote ingest
        logfire.configure(send_to_logfire=False)
        logger.info("logfire: no token — console-only mode")

    # Instrument FastAPI, SQLAlchemy, httpx automatically
    logfire.instrument_fastapi()     # patches app after it's created
    logfire.instrument_sqlalchemy()
    logfire.instrument_httpx()

    _configured = True
    logfire.info("observability.configured", env=settings.APP_ENV)


@lru_cache(maxsize=1)
def get_langfuse() -> Langfuse:
    """
    Cached Langfuse client. Returns a no-op client if keys are missing
    so agent code doesn't need to guard every trace call.

    Every agent run must be traced (N3). If keys aren't set in prod, this
    logs a warning rather than crashing — fix the env, not the code.
    """
    if not settings.LANGFUSE_PUBLIC_KEY:
        logger.warning(
            "langfuse: LANGFUSE_PUBLIC_KEY not set — traces will not be recorded (violates N3 in prod)"
        )
    return Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
    )
