"""
tests/ingestion/test_backpressure.py
-------------------------------------
Purpose:    Backpressure limits are wired, not just declared: arq worker
            concurrency/timeout/retry caps plus the in-process semaphores
            that bound simultaneous PDF parses, indexing runs, and embed
            calls (heavy CPU/GPU work must not pile up).
Dependencies: pytest.
"""

from __future__ import annotations

from app.settings import settings
from app.workers import WorkerSettings
from src.shared.rate_limit import (
    embed_semaphore,
    indexing_semaphore,
    pdf_parse_semaphore,
)


def test_worker_concurrency_caps() -> None:
    """arq must bound parallel jobs, job lifetime, and retry storms."""
    assert WorkerSettings.max_jobs == 4
    assert WorkerSettings.job_timeout == 600
    assert WorkerSettings.max_tries == 3


def test_semaphores_match_settings() -> None:
    """Semaphore capacity must follow the tuned settings knobs."""
    assert indexing_semaphore()._value == settings.MAX_CONCURRENT_INDEXING
    assert pdf_parse_semaphore()._value == settings.MAX_CONCURRENT_PDF_PARSES
    assert embed_semaphore()._value == 4
