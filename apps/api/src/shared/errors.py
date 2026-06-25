"""
shared/errors.py
----------------
Purpose:    Domain error hierarchy + FastAPI exception handlers.
            Raise domain errors in feature code; handlers convert them to HTTP.
Scope:      Error definitions and handler registration only.

Pattern: raise specific domain error → handler maps to HTTP status + log.
Don't catch-and-re-raise generics — let them bubble to the handlers.
"""

from __future__ import annotations

import logging

import logfire
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


# ── Domain errors ─────────────────────────────────────────────────────────────

class ResearchWorkspaceError(Exception):
    """Base for all domain errors. Carries a human-readable message."""
    http_status: int = 500

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail  # internal context, never sent to client


class NotFoundError(ResearchWorkspaceError):
    """Resource (document, chunk, run) doesn't exist or isn't accessible."""
    http_status = 404


class IngestionError(ResearchWorkspaceError):
    """Ingestion pipeline failed for a document."""
    http_status = 422


class RetrievalError(ResearchWorkspaceError):
    """Hybrid search or rerank step failed."""
    http_status = 500


class ModelGatewayError(ResearchWorkspaceError):
    """All LLM providers exhausted or timed out."""
    http_status = 502


class WorkspaceScopeError(ResearchWorkspaceError):
    """Request references data outside the caller's workspace."""
    http_status = 403


# ── Handler registration ──────────────────────────────────────────────────────

def register_error_handlers(app: FastAPI) -> None:
    """
    Call this in create_app() after instantiating FastAPI.
    Maps domain errors → JSON responses with consistent shape.
    """

    @app.exception_handler(ResearchWorkspaceError)
    async def domain_error_handler(request: Request, exc: ResearchWorkspaceError) -> JSONResponse:
        logfire.warning(
            "domain_error",
            error_type=type(exc).__name__,
            message=exc.message,
            path=str(request.url.path),
        )
        if exc.detail:
            # Internal detail logged, not sent to client
            logger.warning("domain error detail: %s", exc.detail)

        return JSONResponse(
            status_code=exc.http_status,
            content={"error": type(exc).__name__, "message": exc.message},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logfire.error(
            "unhandled_error",
            error_type=type(exc).__name__,
            error=str(exc),
            path=str(request.url.path),
        )
        logger.exception("unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "InternalServerError", "message": "An unexpected error occurred."},
        )
