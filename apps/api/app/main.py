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

from contextlib import asynccontextmanager

import logfire
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.app.settings import settings
from apps.api.src.observability.setup import configure as configure_observability
from apps.api.src.shared.database import connect as db_connect, disconnect as db_disconnect
from apps.api.src.shared.errors import register_error_handlers

# Feature routers (add as you build each feature)
# from apps.api.src.ingestion.router import router as ingestion_router
# from apps.api.src.research.router import router as research_router


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────
    configure_observability()         # logfire + langfuse
    await db_connect()                # warm connection pool
    logfire.info("app.started", env=settings.APP_ENV)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    await db_disconnect()
    logfire.info("app.stopped")


# ── Factory ───────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="Agentic Research Workspace API",
        version="0.1.0",
        # Disable OpenAPI in prod if desired; keep on for MVP dev speed
        docs_url="/docs" if settings.APP_DEBUG else None,
        lifespan=lifespan,
    )

    # CORS — tighten origins before going to prod
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],  # Next.js dev server
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Domain error → HTTP response mappings
    register_error_handlers(app)

    # ── Routers ───────────────────────────────────────────────────────────
    # Uncomment as each feature is built:
    # app.include_router(ingestion_router, prefix="/api/ingestion", tags=["ingestion"])
    # app.include_router(research_router,  prefix="/api/research",  tags=["research"])

    # Health check — required for container orchestration
    @app.get("/health", include_in_schema=False)
    async def health() -> dict:
        return {"status": "ok", "env": settings.APP_ENV}

    return app


# ── Entry point (uvicorn apps.api.app.main:app) ───────────────────────────────
app = create_app()
