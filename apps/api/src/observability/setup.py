"""
observability/setup.py
----------------------
Purpose:    Boot Logfire (structured traces + metrics) and Langfuse (agent run tracing, N3).
            Call configure() once at app startup — idempotent after first call.
Dependencies: settings, logfire, langfuse
Scope:      Wiring only. Actual span/trace calls live in each feature module.

Usage:
    from src.observability.setup import configure, get_langfuse
    configure()           # in lifespan
    lf = get_langfuse()   # in agent/retrieval code
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, cast

import logfire
from fastapi import FastAPI
from langfuse import Langfuse, ObservationTypeLiteral, propagate_attributes
from opentelemetry.sdk.trace import TracerProvider

from app.settings import settings

logger = logging.getLogger(__name__)

_configured = False


def configure(app: FastAPI) -> None:
    """
    Wire up Logfire and validate Langfuse credentials.
    Safe to call multiple times — only runs once.
    """
    global _configured
    if _configured:
        return

    # ── Logfire ───────────────────────────────────────────────────────────
    if settings.LOGFIRE_TOKEN:
        _ = logfire.configure(token=settings.LOGFIRE_TOKEN)
    else:
        # Dev mode: log to console, no remote ingest
        _ = logfire.configure(send_to_logfire=False)
        logger.info("logfire: no token — console-only mode")

    # Instrument FastAPI, SQLAlchemy, httpx automatically
    _ = logfire.instrument_fastapi(app)  # patches app after it's created
    _ = logfire.instrument_sqlalchemy()
    _ = logfire.instrument_httpx()

    _configured = True
    logfire.info("observability.configured", env=settings.APP_ENV)


@lru_cache(maxsize=1)
def get_langfuse() -> Langfuse:
    """
    Cached Langfuse client. Returns a client that degrades to a warning if
    keys are missing so agent code doesn't need to guard every trace call.

    Every agent run must be traced (N3). If keys aren't set in prod, this
    logs a warning rather than crashing — fix the env, not the code.

    Uses an isolated TracerProvider so Langfuse never fights Logfire for the
    global one (whichever tool initializes second loses, per Langfuse's
    existing-otel-setup FAQ). OTel context is shared process-wide, so our own
    observations still nest correctly among themselves. ``environment`` tags
    every trace from this process with APP_ENV (dev traces stay out of prod
    dashboards).
    """
    if not settings.LANGFUSE_PUBLIC_KEY:
        logger.warning(
            "langfuse: LANGFUSE_PUBLIC_KEY not set — traces will not be recorded (violates N3 in prod)"
        )
    return Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
        tracer_provider=TracerProvider(),
        environment=settings.APP_ENV,
    )


def flush_langfuse() -> None:
    """Flush pending Langfuse spans (batch exporter) — call at process exit."""
    if not settings.LANGFUSE_PUBLIC_KEY:
        return
    get_langfuse().flush()


@contextmanager
def agent_run_trace(
    run_id: str,
    question: str,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
) -> Iterator[Any]:
    """Trace a single research-agent run in Langfuse (PRD N3).

    Wraps ``run_agent``: records the question as input up front, and expects
    the caller to call ``observation.update(...)`` with the answer and run
    metadata before the context exits. When Langfuse keys are unset, this
    yields a disabled observation and does nothing — no network calls.

    ``user_id`` enables per-user cost/quality views; ``session_id`` groups
    multi-turn conversations (AG-UI thread id). Tags are immutable and set at
    creation, so the feature tag lives here.
    """
    if not settings.LANGFUSE_PUBLIC_KEY:
        yield _NoOpObservation()
        return

    lf = get_langfuse()
    attrs: dict[str, Any] = {"tags": ["feature:research"]}
    if user_id:
        attrs["user_id"] = user_id
    if session_id:
        attrs["session_id"] = session_id

    with (
        propagate_attributes(**attrs),
        lf.start_as_current_observation(
            name="research-agent-run",
            as_type="agent",
            input={"question": question},
            metadata={"run_id": run_id},
        ) as observation,
    ):
        try:
            yield observation
        except Exception:
            observation.update(level="ERROR", status_message="agent run failed")
            raise


@contextmanager
def traced_observation(
    name: str,
    *,
    as_type: ObservationTypeLiteral = "span",
    input: Any = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Langfuse observation around any pipeline step; no-op without keys.

    Nests under whatever observation is active in the current OTel context
    (e.g. a generation inside ``research-agent-run``), or becomes its own
    trace when nothing is active. Marks the observation ERROR on exception.
    """
    if not settings.LANGFUSE_PUBLIC_KEY:
        yield _NoOpObservation()
        return

    lf = get_langfuse()
    # SDK overloads as_type per literal type; our pass-through param is the union.
    with lf.start_as_current_observation(
        name=name,
        as_type=cast(Any, as_type),
        input=input,
        metadata=metadata,
    ) as observation:
        try:
            yield observation
        except Exception:
            observation.update(level="ERROR", status_message=f"{name} failed")
            raise


class _NoOpObservation:
    """Stand-in observation for when Langfuse tracing is disabled.

    Absorbs ``update()`` calls so callers don't need to guard against the
    disabled case.
    """

    def update(self, **kwargs: Any) -> None:
        return
