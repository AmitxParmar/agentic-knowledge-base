"""
tests/shared/test_model_gateway_speech.py
------------------------------------------
Purpose:    Offline tests for model_gateway.speech() — the hosted Groq
            Orpheus TTS call (ADR-006 amendment). Requests are routed
            through httpx.MockTransport via the _speech_client seam, so no
            network and no API key are needed.
Dependencies: pytest, httpx.
Scope:      Request shape, success bytes, typed error mapping (429/5xx/network).
"""

from __future__ import annotations

import json

import httpx
import pytest

from src.shared import model_gateway
from src.shared.model_gateway import ProviderError, RateLimitError, speech


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    """Route speech() through a MockTransport; returns the captured requests."""
    seen: list[httpx.Request] = []

    def _record_and_respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def _client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(_record_and_respond))

    monkeypatch.setattr(model_gateway, "_speech_client", _client)
    return seen


async def test_speech_returns_wav_bytes_with_expected_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_client(
        monkeypatch, lambda request: httpx.Response(200, content=b"RIFFwavdata")
    )

    result = await speech("Hello there.", voice="hannah")

    assert result == b"RIFFwavdata"
    assert len(captured) == 1
    request = captured[0]
    assert str(request.url) == "https://api.groq.com/openai/v1/audio/speech"
    assert request.headers["authorization"].startswith("Bearer ")
    body = json.loads(request.content)
    assert body["input"] == "Hello there."
    assert body["voice"] == "hannah"
    assert body["response_format"] == "wav"
    assert body["model"] == model_gateway.settings.VOICE_TTS_MODEL


async def test_speech_maps_429_to_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, lambda request: httpx.Response(429, json={"error": "slow down"}))

    with pytest.raises(RateLimitError):
        await speech("Hello")


async def test_speech_maps_server_error_to_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, lambda request: httpx.Response(500, text="boom"))

    with pytest.raises(ProviderError):
        await speech("Hello")


async def test_speech_maps_network_error_to_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    _patch_client(monkeypatch, _boom)

    with pytest.raises(ProviderError):
        await speech("Hello")
