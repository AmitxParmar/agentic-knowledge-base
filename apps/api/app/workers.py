"""
worker/main.py
--------------
Purpose:    arq worker entry point. Runs ingestion jobs asynchronously (N4).
            Upload requests return immediately; this processes them in the background.
Dependencies: arq, settings, ingestion/pipeline
Scope:      Job registration only. Pipeline logic lives in src/ingestion/pipeline.py.

Start with: arq app.workers.WorkerSettings
"""

from __future__ import annotations

from typing import Any, ClassVar

import logfire
from arq.connections import RedisSettings

import src.shared.models  # noqa: F401
from app.settings import settings
from src.ingestion.pipeline import run_ingestion_job


async def startup(ctx: dict[str, Any]) -> None:
    """
    Runs once when worker boots.
    Steps:
      1. Configure logfire for structured logging (no FastAPI app in worker context)
      2. Store worker metadata in context for job access if needed
    """
    # Initialize logfire for worker process (no FastAPI app, so configure directly)
    if settings.LOGFIRE_TOKEN:
        _ = logfire.configure(token=settings.LOGFIRE_TOKEN)
    else:
        # Dev mode: console-only logging
        _ = logfire.configure(send_to_logfire=False)
    
    # Log worker startup
    _ = logfire.info("worker.started", env=settings.APP_ENV)


async def shutdown(ctx: dict[str, Any]) -> None:
    """
    Runs once when worker stops.
    Steps:
      1. Clean up any open resources
      2. Log shutdown event
    """
    _ = logfire.info("worker.stopped")


class WorkerSettings:
    """
    arq worker configuration.
    Defines job functions, lifecycle hooks, Redis connection, and resource limits.
    """
    
    # Job functions to register (arq expects callables)
    # run_ingestion_job has signature: (ctx: dict[str, Any], *, document_id: str) -> None
    functions: ClassVar = [run_ingestion_job]

    # Lifecycle hooks
    on_startup: ClassVar = startup
    on_shutdown: ClassVar = shutdown

    # Redis connection for job queue
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(settings.REDIS_URL)

    # Resource limits (tune based on actual load data)
    max_jobs: int = 4          # max concurrent jobs per worker
    job_timeout: int = 600     # 10min ceiling per ingestion job

    # Retry policy — a transient provider failure no longer permanently fails
    # the document. The job is attempted up to max_tries times (initial + 2
    # retries) before the row lands in `failed`.
    max_tries: int = 3
