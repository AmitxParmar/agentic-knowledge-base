"""
worker/main.py
--------------
Purpose:    arq worker entry point. Runs ingestion jobs asynchronously (N4).
            Upload requests return immediately; this processes them in the background.
Dependencies: arq, settings, ingestion pipeline (src/ingestion/)
Scope:      Job registration only. Pipeline logic lives in src/ingestion/.

Start with: arq apps.worker.main.WorkerSettings
"""

from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings

from apps.api.app.settings import settings

# Import job functions as they're built:
# from src.ingestion.pipeline import run_ingestion_job


# ── Job functions (registered below) ──────────────────────────────────────────

def startup(ctx: dict) -> None:
    """Runs once when worker boots — set up shared resources here."""
    from src.observability.setup import configure
    configure()


async def shutdown(ctx: dict) -> None:
    """Runs on clean worker shutdown."""
    pass


# ── Worker settings ───────────────────────────────────────────────────────────

class WorkerSettings:
    functions = [
        # run_ingestion_job,   # uncomment when src/ingestion/pipeline.py is built
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 4          # ponytail: tune when you have load data
    job_timeout = 600     # 10min ceiling per ingestion job
