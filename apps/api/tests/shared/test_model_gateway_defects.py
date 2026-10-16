"""
tests/shared/test_model_gateway_defects.py
-------------------------------------------
Regression tests for the gateway fallback/retry defects:
- #5: a 429 surviving fallback exhaustion must surface as RateLimitError
      (not untyped RetryableError → generic AGENT_ERROR).
- #6: fast transient failures are actually retried inside the gateway SLA.
- #7: the per-provider timeout is delegated to litellm (so the fallback
      chain runs), litellm timeouts map to ProviderError, and a completely
      unusable tool response gets exactly one retry.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import litellm
import pytest

from src.shared.model_gateway import (
    ProviderError,
    RateLimitError,
    RetryableError,
    complete,
    complete_with_tools,
)


def _resp(content: str | None = "ok", tool_calls: list | None = None) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))],
        usage=SimpleNamespace(total_tokens=5, prompt_tokens=3, completion_tokens=2),
        model="groq/llama-3.3-70b-versatile",
    )


def _fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    # Step 1: shrink backoff so retry tests run in milliseconds, not seconds.
    from app.settings import settings

    monkeypatch.setattr(settings, "RETRY_BASE_DELAY", 0.001)
    monkeypatch.setattr(settings, "RETRY_MAX_DELAY", 0.001)


# ── #5: rate-limit classification survives fallback exhaustion ─────────────────


@pytest.mark.asyncio
async def test_rate_limit_text_after_fallbacks_is_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # LiteLLM re-raises a plain Exception once primary + fallback are spent —
    # the 429 status attribute is gone, only the message remains.
    _fast_retries(monkeypatch)
    failing = AsyncMock(side_effect=Exception("litellm.RateLimitError: 429 rate limit exceeded"))
    monkeypatch.setattr(litellm, "acompletion", failing)
    with pytest.raises(RateLimitError):
        await complete([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_rate_limit_status_attr_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    _fast_retries(monkeypatch)
    exc = Exception("slow down")
    exc.status_code = 429  # type: ignore[attr-defined]
    monkeypatch.setattr(litellm, "acompletion", AsyncMock(side_effect=exc))
    with pytest.raises(RateLimitError):
        await complete([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_transient_5xx_stays_retryable_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    _fast_retries(monkeypatch)
    exc = Exception("upstream 503")
    exc.status_code = 503  # type: ignore[attr-defined]
    monkeypatch.setattr(litellm, "acompletion", AsyncMock(side_effect=exc))
    with pytest.raises(RetryableError):
        await complete([{"role": "user", "content": "hi"}])


# ── #6: fast transient failures are retried ───────────────────────────────────


@pytest.mark.asyncio
async def test_connection_errors_retried_then_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fast_retries(monkeypatch)
    flaky = AsyncMock(
        side_effect=[ConnectionError("reset"), ConnectionError("reset"), _resp("recovered")]
    )
    monkeypatch.setattr(litellm, "acompletion", flaky)
    assert await complete([{"role": "user", "content": "hi"}]) == "recovered"
    assert flaky.await_count == 3


# ── #7: timeout delegated to litellm; unusable responses retried once ─────────


@pytest.mark.asyncio
async def test_provider_timeout_passed_to_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    # Step 1: capture the kwargs — the timeout must ride inside litellm so a
    # slow primary still lets the fallback attempt run (a wait_for around the
    # call would cancel the fallback loop instead).
    from app.settings import settings

    seen: dict[str, Any] = {}

    async def fake_acompletion(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return _resp("ok")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    await complete([{"role": "user", "content": "hi"}])
    # Step 2: the timeout rides inside litellm, and the OpenRouter fallback
    # is still attached for the timeout path.
    assert seen["timeout"] == settings.MODEL_GATEWAY_PROVIDER_TIMEOUT
    assert seen["fallbacks"] == [f"openrouter/{settings.MODEL_GATEWAY_OPENROUTER_MODEL}"]


@pytest.mark.asyncio
async def test_litellm_timeout_maps_to_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fast_retries(monkeypatch)
    monkeypatch.setattr(litellm, "acompletion", AsyncMock(side_effect=TimeoutError()))
    with pytest.raises(ProviderError, match="timed out"):
        await complete([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_unusable_tool_response_retried_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Step 1: first cycle returns garbage (no content, no valid calls)...
    # Step 2: ...the gateway retries once and returns the good response.
    tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
    responder = AsyncMock(side_effect=[_resp(None, None), _resp("final")])
    monkeypatch.setattr(litellm, "acompletion", responder)
    out = await complete_with_tools([{"role": "user", "content": "hi"}], tools=tools)
    assert out.content == "final"
    assert responder.await_count == 2


@pytest.mark.asyncio
async def test_unusable_tool_response_gives_up_after_one_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
    responder = AsyncMock(side_effect=[_resp(None, None), _resp(None, None)])
    monkeypatch.setattr(litellm, "acompletion", responder)
    out = await complete_with_tools([{"role": "user", "content": "hi"}], tools=tools)
    assert out.content is None
    assert responder.await_count == 2


@pytest.mark.asyncio
async def test_empty_content_without_tools_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # complete() callers handle empty text themselves — no retry when no
    # tools were requested.
    responder = AsyncMock(side_effect=[_resp("")])
    monkeypatch.setattr(litellm, "acompletion", responder)
    assert await complete([{"role": "user", "content": "hi"}]) == ""
    assert responder.await_count == 1
