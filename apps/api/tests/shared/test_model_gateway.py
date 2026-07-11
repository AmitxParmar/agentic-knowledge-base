"""
Smoke test: model gateway provider chain resolves correctly.
Does NOT make real API calls — just checks config + client construction.
"""

import pytest

from app.settings import settings
from src.shared.model_gateway import _provider_chain


def test_groq_primary_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MODEL_GATEWAY_PROVIDER", "groq")
    chain = _provider_chain()
    names = [p[0] for p in chain]
    assert names[0] == "groq", "Groq must be first when provider=groq"
    assert names[1] == "openrouter", "OpenRouter must be fallback"


def test_openrouter_primary_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MODEL_GATEWAY_PROVIDER", "openrouter")
    chain = _provider_chain()
    assert chain[0][0] == "openrouter"
    assert chain[1][0] == "groq"


def test_chain_has_two_providers() -> None:
    # ponytail: if a third provider is added, update this test
    assert len(_provider_chain()) == 2
