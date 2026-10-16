"""
tests/shared/test_circuit_breaker.py
-------------------------------------
Circuit-breaker state machine (deterministic fake clock) plus gateway
wiring: tripped primary is skipped, double-trip fails fast, failures and
successes move the breaker.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import litellm
import pytest

import src.shared.model_gateway as gateway
from src.shared.circuit_breaker import CircuitBreaker
from src.shared.model_gateway import ProviderError, RetryableError, _provider_of, complete


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    # Step 1: pin time.monotonic to a mutable cell tests advance by hand.
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    return now


def test_closed_breaker_allows() -> None:
    assert CircuitBreaker().allow("groq") is True


def test_opens_after_threshold_in_window(clock: list[float]) -> None:
    breaker = CircuitBreaker(failure_threshold=3, window_seconds=30.0)
    for _ in range(3):
        breaker.record_failure("groq")
    assert breaker.allow("groq") is False


def test_old_failures_slide_out_of_window(clock: list[float]) -> None:
    breaker = CircuitBreaker(failure_threshold=2, window_seconds=10.0)
    breaker.record_failure("groq")
    clock[0] += 11.0
    breaker.record_failure("groq")
    assert breaker.allow("groq") is True


def test_cooldown_admits_single_probe(clock: list[float]) -> None:
    breaker = CircuitBreaker(failure_threshold=1, window_seconds=30.0, cooldown_seconds=60.0)
    breaker.record_failure("groq")
    assert breaker.allow("groq") is False
    clock[0] += 61.0
    # Step 1: first caller after cooldown gets the probe...
    assert breaker.allow("groq") is True
    # Step 2: ...concurrent callers wait for the verdict.
    assert breaker.allow("groq") is False


def test_probe_success_closes(clock: list[float]) -> None:
    breaker = CircuitBreaker(failure_threshold=1, window_seconds=30.0, cooldown_seconds=60.0)
    breaker.record_failure("groq")
    clock[0] += 61.0
    assert breaker.allow("groq") is True
    breaker.record_success("groq")
    assert breaker.allow("groq") is True
    assert breaker.allow("groq") is True


def test_probe_failure_reopens(clock: list[float]) -> None:
    breaker = CircuitBreaker(failure_threshold=5, window_seconds=30.0, cooldown_seconds=60.0)
    breaker.record_failure("groq")
    breaker.record_failure("groq")
    breaker.record_failure("groq")
    breaker.record_failure("groq")
    breaker.record_failure("groq")
    clock[0] += 61.0
    assert breaker.allow("groq") is True
    breaker.record_failure("groq")
    assert breaker.allow("groq") is False


def test_provider_of() -> None:
    assert _provider_of("groq/llama-3.3-70b-versatile") == "groq"
    assert _provider_of("openrouter/mistralai/mistral-7b-instruct") == "openrouter"
    assert _provider_of("bare-model") == "bare-model"


def _resp(content: str = "ok") -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))],
        usage=SimpleNamespace(total_tokens=5, prompt_tokens=3, completion_tokens=2),
        model="openrouter/mistralai/mistral-7b-instruct",
    )


@pytest.mark.asyncio
async def test_tripped_primary_leads_with_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Step 1: trip groq on a throwaway breaker and install it in the gateway.
    test_breaker = CircuitBreaker(failure_threshold=1, window_seconds=30.0)
    test_breaker.record_failure("groq")
    monkeypatch.setattr(gateway, "breaker", test_breaker)
    # Step 2: the call must go straight to OpenRouter with no further chain.
    seen: dict[str, Any] = {}

    async def fake_acompletion(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return _resp()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    assert await complete([{"role": "user", "content": "hi"}]) == "ok"
    assert seen["model"].startswith("openrouter/")
    assert seen["fallbacks"] == []


@pytest.mark.asyncio
async def test_double_trip_fails_fast_without_calling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_breaker = CircuitBreaker(failure_threshold=1, window_seconds=30.0)
    test_breaker.record_failure("groq")
    test_breaker.record_failure("openrouter")
    monkeypatch.setattr(gateway, "breaker", test_breaker)
    spy = AsyncMock(side_effect=AssertionError("must not call any provider"))
    monkeypatch.setattr(litellm, "acompletion", spy)
    with pytest.raises(ProviderError, match="temporarily unavailable"):
        await complete([{"role": "user", "content": "hi"}])
    assert spy.await_count == 0


@pytest.mark.asyncio
async def test_gateway_failures_trip_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    # Step 1: two failing cycles trip a threshold-2 breaker for groq...
    test_breaker = CircuitBreaker(failure_threshold=2, window_seconds=300.0)
    monkeypatch.setattr(gateway, "breaker", test_breaker)
    seen: dict[str, Any] = {}

    async def flaky(**kwargs: Any) -> Any:
        seen.update(kwargs)
        raise ConnectionError("down")

    monkeypatch.setattr(litellm, "acompletion", flaky)
    from app.settings import settings

    monkeypatch.setattr(settings, "RETRY_BASE_DELAY", 0.001)
    monkeypatch.setattr(settings, "RETRY_MAX_DELAY", 0.001)
    with pytest.raises(RetryableError):
        await complete([{"role": "user", "content": "hi"}])
    with pytest.raises(RetryableError):
        await complete([{"role": "user", "content": "hi"}])
    # Step 2: ...so the next call skips groq and leads with the fallback.
    with pytest.raises(RetryableError):
        await complete([{"role": "user", "content": "hi"}])
    assert seen["model"].startswith("openrouter/")
    assert seen["fallbacks"] == []
    # Step 3: tripping the fallback too fails fast without any provider call.
    test_breaker.record_failure("openrouter")
    test_breaker.record_failure("openrouter")
    spy = AsyncMock(side_effect=AssertionError("must not call any provider"))
    monkeypatch.setattr(litellm, "acompletion", spy)
    with pytest.raises(ProviderError, match="temporarily unavailable"):
        await complete([{"role": "user", "content": "hi"}])
    assert spy.await_count == 0


def test_snapshot_reports_state_without_consuming_probe(clock: list[float]) -> None:
    breaker = CircuitBreaker(failure_threshold=1, window_seconds=30.0, cooldown_seconds=60.0)

    # Step 1: untouched providers are absent; a healthy one reports closed.
    assert breaker.snapshot() == {}
    breaker.record_success("groq")
    assert breaker.snapshot()["groq"]["state"] == "closed"

    # Step 2: a tripped provider reports open + retry countdown.
    breaker.record_failure("openrouter")
    view = breaker.snapshot()["openrouter"]
    assert view["state"] == "open"
    assert view["retry_after_seconds"] > 0

    # Step 3: after cooldown the snapshot reports half-open...
    clock[0] += 61.0
    assert breaker.snapshot()["openrouter"]["state"] == "half-open"
    # ...without consuming the probe slot (health checks must not spend it).
    assert breaker.allow("openrouter") is True
