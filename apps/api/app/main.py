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
from src.research.conversations_router import router as conversations_router
from src.research.router import router as research_router
from src.research.voice_router import router as voice_router
from src.shared.database import connect as db_connect
from src.shared.database import disconnect as db_disconnect
from src.shared.errors import register_error_handlers
from src.shared.redis import close_redis

logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────
    configure_observability(app)  # logfire + langfuse
    await db_connect()  # warm connection pool
    logfire.info("app.started", env=settings.APP_ENV)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    await db_disconnect()
    await close_redis()
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
        request_id = str(uuid.uuid4())
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
