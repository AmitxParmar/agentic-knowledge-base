"""
shared/retry.py
---------------
Retry helper with exponential backoff + jitter for transient failures.
"""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.settings import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryableError(Exception):
    """Base for errors that should trigger retry."""
    pass


class NonRetryableError(Exception):
    """Base for errors that should NOT trigger retry."""
    pass


# Common retryable exception types
DEFAULT_RETRYABLE_EXCEPTIONS = (
    asyncio.TimeoutError,
    ConnectionError,
    IOError,
    OSError,
)


async def with_retry(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    max_attempts: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
    retryable_exceptions: tuple[type[Exception], ...] = DEFAULT_RETRYABLE_EXCEPTIONS,
    **kwargs: Any,
) -> T:
    """
    Execute an async function with exponential backoff + jitter retry logic.

    Args:
        func: Async function to execute
        *args: Positional arguments for func
        max_attempts: Maximum retry attempts (default from settings)
        base_delay: Initial delay in seconds (default from settings)
        max_delay: Maximum delay cap in seconds (default from settings)
        retryable_exceptions: Exception types that trigger retry
        **kwargs: Keyword arguments for func

    Returns:
        Result of func

    Raises:
        Last exception if all retries exhausted
        NonRetryableError immediately without retry
    """
    max_attempts = max_attempts or settings.RETRY_MAX_ATTEMPTS
    base_delay = base_delay or settings.RETRY_BASE_DELAY
    max_delay = max_delay or settings.RETRY_MAX_DELAY

    attempt = 0
    while True:
        try:
            return await func(*args, **kwargs)
        except NonRetryableError:
            # Re-raise immediately without retry
            raise
        except retryable_exceptions as exc:
            attempt += 1
            if attempt >= max_attempts:
                logger.warning(
                    "retry.exhausted: %s/%s attempts, error=%s",
                    attempt,
                    max_attempts,
                    str(exc),
                )
                raise
            # Exponential backoff with jitter: base * 2^attempt + jitter
            delay = min(base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.1), settings.RETRY_MAX_DELAY)
            logger.warning(
                    "retry.attempt %s/%s after %.2fs: %s",
                    attempt,
                    max_attempts,
                    delay,
                    str(exc),
                )
            await asyncio.sleep(delay)
        except Exception as exc:
            # Unknown exception - don't retry by default
            logger.warning(
                "retry.non_retryable: %s: %s",
                type(exc).__name__,
                str(exc),
            )
            raise


def is_retryable_status(status_code: int) -> bool:
    """Check if HTTP status code is retryable."""
    return status_code == 429 or 500 <= status_code < 600


def is_retryable_exception(exc: Exception) -> bool:
    """Check if exception is a retryable error type."""
    if isinstance(exc, NonRetryableError):
        return False
    if isinstance(exc, RetryableError):
        return True
    if isinstance(exc, DEFAULT_RETRYABLE_EXCEPTIONS):
        return True
    # Check for HTTP status codes in common exception attributes
    for attr in ("status_code", "http_status", "status"):
        status = getattr(exc, attr, None)
        if isinstance(status, int) and is_retryable_status(status):
            return True
    # Check error message for rate limit indicators
    text = str(exc).lower()
    return any(kw in text for kw in ("rate limit", "rate_limit", "429", "too many requests"))