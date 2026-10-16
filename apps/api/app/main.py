"""
main.py
-------
Purpose:    FastAPI application factory.
            Wires lifespan, middleware, routers, and error handlers.
            Does not contain any business logic — that lives in src/.
Dependencies: settings, observability, database, routers
Scope:      App creation and startup/shutdown only.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import logfire
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

# ── ORM model registration ─────────────────────────────────────────────────
import src.shared.models  # noqa: F401
from app.settings import settings
from src.ingestion.router import router as ingestion_router
from src.observability.setup import configure as configure_observability
from src.observability.setup import flush_langfuse
from src.research.checkpoint import close as close_checkpoint_pool
from src.research.conversations_router import router as conversations_router
from src.research.router import router as research_router
from src.research.voice_router import router as voice_router
from src.shared.database import connect as db_connect
from src.shared.database import disconnect as db_disconnect
from src.shared.errors import register_error_handlers
from src.shared.redis import close_redis

logger = logging.getLogger(__name__)

# ── Readiness advisories (non-fatal) ─────────────────────────────────────────
# Cheap probes that operators want visible but that must NOT flip readiness:
# a tripped provider breaker or a busy disk should degrade answers, not cause
# Render to recycle an otherwise healthy instance.

_EMB_VERSION_CACHE: dict[str, Any] = {"at": 0.0, "value": "unknown"}


async def _embedding_versions() -> str:
    """Distinct embedding models stored on chunks (60s in-process cache).

    Mixed models inside one pgvector column silently degrade similarity
    (different embedding spaces), so the check is surfaced instead of hidden.
    """
    # Step 1: serve from cache — readiness probes hit this every few seconds.
    now = time.monotonic()
    if now - float(_EMB_VERSION_CACHE["at"]) < 60.0:
        return str(_EMB_VERSION_CACHE["value"])
    # Step 2: bounded DISTINCT scan; any failure reports as unknown, never 5xx.
    import asyncio

    try:
        from sqlalchemy import select

        from src.ingestion.models import Chunk
        from src.shared.database import SessionLocal

        async with SessionLocal() as session:
            result = await asyncio.wait_for(
                session.execute(
                    select(Chunk.embedding_model)
                    .where(Chunk.embedding_model.is_not(None))
                    .distinct()
                    .limit(5)
                ),
                timeout=2,
            )
            models = sorted(str(row[0]) for row in result.all())
        if not models:
            value = "unversioned (pre-tracking corpus)"
        elif len(models) == 1:
            value = f"ok ({models[0]})"
        else:
            value = f"MIXED ({', '.join(models)})"
            logger.warning("chunks carry %d embedding models: %s", len(models), models)
    except Exception as exc:
        value = f"unknown: {type(exc).__name__}"
    # Step 3: stamp the cache and return.
    _EMB_VERSION_CACHE.update({"at": now, "value": value})
    return value


def _disk_usage() -> str:
    """Upload-volume usage percent — advisory, skipped when R2 is the store."""
    # Step 1: managed object storage has no local volume to watch.
    if settings.r2_enabled:
        return "r2 (managed)"
    # Step 2: measure the filesystem that holds UPLOAD_DIR (may not exist yet).
    import shutil
    from pathlib import Path

    path = Path(settings.UPLOAD_DIR)
    probe = path if path.exists() else path.parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError as exc:
        return f"unknown: {type(exc).__name__}"
    pct = round(usage.used / usage.total * 100) if usage.total else 0
    # Step 3: log near-full volumes for ops; still advisory to readiness.
    if pct >= 90:
        logger.warning("upload volume %s is %d%% full", probe, pct)
    return f"{pct}% used"


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────
    configure_observability(app)  # logfire + langfuse
    await db_connect()  # warm connection pool
    logfire.info("app.started", env=settings.APP_ENV)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    await close_checkpoint_pool()
    await db_disconnect()
    await close_redis()
    flush_langfuse()  # push tail spans before the batch exporter dies with the process
    logfire.info("app.stopped")


# ── Factory ───────────────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agentic Research Workspace API",
        version="0.1.0",
        docs_url="/docs" if settings.APP_DEBUG else None,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Structured request logging middleware ─────────────────────────────
    @app.middleware("http")
    async def request_logging(request: Request, call_next: Any) -> Response:
        # Step 1: honor a caller-supplied ID so traces correlate across
        # services (Vercel → Render); mint one when the caller sends none.
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        start = time.monotonic()
        request.state.request_id = request_id

        response: Response = await call_next(request)

        latency_ms = round((time.monotonic() - start) * 1000)
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "route": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response

    # Domain error → HTTP response mappings
    register_error_handlers(app)

    # ── Routers ───────────────────────────────────────────────────────────
    app.include_router(ingestion_router, prefix="/api/ingestion", tags=["ingestion"])
    app.include_router(research_router, prefix="/api/research", tags=["research"])
    app.include_router(voice_router, prefix="/api/research", tags=["voice"])
    app.include_router(conversations_router, prefix="/api/conversations", tags=["conversations"])

    # ── Health endpoints ──────────────────────────────────────────────────

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        """Liveness: always returns 200. Used by Render to restart crashed instances."""
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> Response:
        """
        Readiness: verifies Redis and DB connectivity.
        Returns 200 only when all dependencies are reachable.
        Provider-breaker, embedding-version, and disk entries are advisory —
        they are reported but never flip the status code.
        """
        import asyncio

        checks: dict[str, str] = {}
        ok = True

        # Redis check
        try:
            from src.shared.redis import redis_client as _get_redis

            r = await asyncio.wait_for(_get_redis(), timeout=2)
            if r and r is not False:
                await asyncio.wait_for(r.ping(), timeout=2)
                checks["redis"] = "ok"
            else:
                checks["redis"] = "unavailable"
                ok = False
        except Exception as exc:
            checks["redis"] = f"error: {type(exc).__name__}"
            ok = False

        # DB check
        try:
            from sqlalchemy import text

            from src.shared.database import SessionLocal

            async with SessionLocal() as session:
                await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=2)
            checks["db"] = "ok"
        except Exception as exc:
            checks["db"] = f"error: {type(exc).__name__}"
            ok = False

        # Embedding dependency (Cohere) — cached probe, see embedder.health_check
        try:
            from src.retrieval.embedder import health_check

            status = await asyncio.wait_for(health_check(), timeout=7)
            checks["embeddings"] = status
            if status not in ("ok", "skipped (dev fallback)"):
                ok = False
        except Exception as exc:
            checks["embeddings"] = f"error: {type(exc).__name__}"
            ok = False

        # Advisory: model-provider breaker states (external service — an open
        # breaker means degraded answers, not an unhealthy API instance).
        try:
            from src.shared.circuit_breaker import breaker

            snapshot = breaker.snapshot()
            checks["model_providers"] = (
                ", ".join(f"{p}={s['state']}" for p, s in snapshot.items())
                if snapshot
                else "untested"
            )
        except Exception as exc:
            checks["model_providers"] = f"error: {type(exc).__name__}"

        # Advisory: mixed embedding models inside the pgvector column would
        # silently degrade similarity — surface it, don't hide it.
        checks["embedding_versions"] = await _embedding_versions()
        # Advisory: upload-volume headroom (local disk mode only).
        checks["upload_disk"] = _disk_usage()

        status_code = 200 if ok else 503
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=status_code,
            content={"status": "ok" if ok else "degraded", "checks": checks},
        )

    # Legacy health + home endpoints
    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.APP_ENV}

    @app.get("/", include_in_schema=False)
    async def home() -> dict[str, str]:
        return {
            "status": "ok",
            "env": settings.APP_ENV,
            "docs": "visit /docs for api documentation",
        }

    # Debug-only LLM smoke test. In production it would burn provider quota
    # and echo provider errors, so it exists only when APP_DEBUG=true.
    if settings.APP_DEBUG:

        @app.get("/test-llm", include_in_schema=False)
        async def test_llm() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            from src.shared.model_gateway import complete

            try:
                response = await complete(
                    [{"role": "user", "content": "Say hello in one sentence."}],
                    max_tokens=100,
                )
                return {"status": "ok", "response": response}
            except Exception as exc:
                return {"status": "error", "error": str(exc)}

    return app


# ── Entry point (uvicorn app.main:app) ───────────────────────────────
app = create_app()
