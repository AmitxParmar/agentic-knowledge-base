"""
tests/shared/test_model_gateway_streaming.py
---------------------------------------------
Token-level streaming: deltas forward in order, usage arrives last, breaker
and typed errors behave like the blocking path.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import litellm
import pytest

import src.shared.model_gateway as gateway
from src.shared.circuit_breaker import CircuitBreaker
from src.shared.model_gateway import (
    ProviderError,
    RateLimitError,
    StreamUsage,
    complete_stream,
)


def _chunk(text: str | None = None, usage: Any = None) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text))],
        usage=usage,
    )


def _usage(total: int = 9) -> Any:
    return SimpleNamespace(total_tokens=total, prompt_tokens=6, completion_tokens=3)


async def _collect(stream: Any) -> tuple[str, StreamUsage | None]:
    # Step 1: drain the stream, separating text deltas from the usage trailer.
    texts: list[str] = []
    usage: StreamUsage | None = None
    async for part in stream:
        if isinstance(part, str):
            texts.append(part)
        else:
            usage = part
    return "".join(texts), usage


@pytest.mark.asyncio
async def test_stream_forwards_deltas_then_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acompletion(**kwargs: Any) -> Any:
        async def gen() -> Any:
            yield _chunk("Hello ")
            yield _chunk("world")
            yield _chunk(None, _usage(9))

        return gen()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    text, usage = await _collect(complete_stream([{"role": "user", "content": "hi"}]))
    assert text == "Hello world"
    assert usage is not None and usage.total_tokens == 9
    assert usage.prompt_tokens == 6 and usage.completion_tokens == 3


@pytest.mark.asyncio
async def test_stream_sends_provider_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_acompletion(**kwargs: Any) -> Any:
        seen.update(kwargs)

        async def gen() -> Any:
            yield _chunk("x")

        return gen()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    await _collect(complete_stream([{"role": "user", "content": "hi"}]))
    from app.settings import settings

    assert seen["stream"] is True
    assert seen["timeout"] == settings.MODEL_GATEWAY_PROVIDER_TIMEOUT
    assert seen["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_stream_open_failure_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing(**kwargs: Any) -> Any:
        raise Exception("429 rate limit exceeded")

    monkeypatch.setattr(litellm, "acompletion", failing)
    with pytest.raises(RateLimitError):
        await _collect(complete_stream([{"role": "user", "content": "hi"}]))


@pytest.mark.asyncio
async def test_stream_mid_failure_raises_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acompletion(**kwargs: Any) -> Any:
        async def gen() -> Any:
            yield _chunk("partial")
            raise Exception("boom")

        return gen()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    with pytest.raises(ProviderError):
        await _collect(complete_stream([{"role": "user", "content": "hi"}]))


@pytest.mark.asyncio
async def test_stream_respects_open_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    test_breaker = CircuitBreaker(failure_threshold=1, window_seconds=30.0)
    test_breaker.record_failure("groq")
    test_breaker.record_failure("openrouter")
    monkeypatch.setattr(gateway, "breaker", test_breaker)
    spy = AsyncMock(side_effect=AssertionError("must not call any provider"))
    monkeypatch.setattr(litellm, "acompletion", spy)
    with pytest.raises(ProviderError, match="temporarily unavailable"):
        await _collect(complete_stream([{"role": "user", "content": "hi"}]))
    assert spy.await_count == 0
