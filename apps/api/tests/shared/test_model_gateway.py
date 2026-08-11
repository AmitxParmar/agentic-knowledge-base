"""
Smoke test: model gateway LiteLLM wiring.
Does NOT make real API calls — just checks model-string resolution,
which is the unit of work that determines provider routing.
"""

import pytest

from app.settings import settings
from src.shared.model_gateway import (
    ProviderError,
    RateLimitError,
    _classify_provider_error,
    _is_rate_limit,
    _resolve_models,
)


def test_default_resolution_groq_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    # When the caller supplies no explicit model, Settings drives primary+fallback.
    monkeypatch.setattr(settings, "MODEL_GATEWAY_PROVIDER", "groq")
    monkeypatch.setattr(settings, "MODEL_GATEWAY_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setattr(settings, "MODEL_GATEWAY_OPENROUTER_MODEL", "mistralai/mistral-7b-instruct")

    primary, fallback = _resolve_models(None)
    assert primary == "groq/llama-3.3-70b-versatile", "primary must be prefixed by active provider"
    assert fallback == "openrouter/mistralai/mistral-7b-instruct", "fallback must be OpenRouter"


def test_default_resolution_openrouter_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MODEL_GATEWAY_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "MODEL_GATEWAY_MODEL", "anthropic/claude-sonnet-4")

    primary, _ = _resolve_models(None)
    assert primary.startswith("openrouter/"), "primary must follow the active provider prefix"


def test_explicit_model_keeps_openrouter_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # A caller-supplied fully-qualified model becomes primary; OpenRouter stays fallback.
    monkeypatch.setattr(settings, "MODEL_GATEWAY_OPENROUTER_MODEL", "mistralai/mistral-7b-instruct")

    primary, fallback = _resolve_models("groq/llama-3.3-70b-versatile")
    assert primary == "groq/llama-3.3-70b-versatile"
    assert fallback.startswith("openrouter/"), "explicit model must still retain an OpenRouter fallback"


def test_rate_limit_detection_by_status_code() -> None:
    class FakeRateLimit(Exception):
        status_code = 429

    assert _is_rate_limit(FakeRateLimit("rate limit exceeded")), "HTTP 429 must classify as rate limit"


def test_rate_limit_detection_by_message() -> None:
    class FakeRateLimit(Exception):
        pass

    assert _is_rate_limit(FakeRateLimit("Too many requests: rate limit reached for model"))


def test_rate_limit_classified_as_rate_limit_error() -> None:
    class FakeRateLimit(Exception):
        status_code = 429

    error = _classify_provider_error(FakeRateLimit("rate limit"))
    assert isinstance(error, RateLimitError)
    assert not isinstance(error, ProviderError), "rate limit must not collapse into a generic provider error"


def test_generic_failure_classified_as_provider_error() -> None:
    error = _classify_provider_error(RuntimeError("connection reset"))
    assert isinstance(error, ProviderError)