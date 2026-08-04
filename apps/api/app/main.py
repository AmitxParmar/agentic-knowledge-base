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

from app.settings import settings
from src.ingestion.router import router as ingestion_router
from src.observability.setup import configure as configure_observability
from src.research.router import router as research_router
from src.shared.database import connect as db_connect
from src.shared.database import disconnect as db_disconnect
from src.shared.errors import register_error_handlers

# ── ORM model registration ─────────────────────────────────────────────────
# Import the central registry so SQLAlchemy's declarative Base discovers
# all mapped classes before any mapper is configured.
import src.shared.models  # noqa: F401


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────
    configure_observability(app)  # logfire + langfuse
    await db_connect()  # warm connection pool
    # Embeddings live in Postgres (pgvector) — no in-memory index to rebuild.
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

    # CORS — origins from settings (dev: localhost:3000, prod: Vercel/deployed frontend)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Domain error → HTTP response mappings
    register_error_handlers(app)

    # ── Routers ───────────────────────────────────────────────────────────
    app.include_router(ingestion_router, prefix="/api/ingestion", tags=["ingestion"])
    app.include_router(research_router, prefix="/api/research", tags=["research"])

    # Health check — required for container orchestration
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
