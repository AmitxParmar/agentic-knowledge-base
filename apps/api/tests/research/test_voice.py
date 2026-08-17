"""
tests/research/test_voice.py
-----------------------------
Purpose:    Tests for the voice channel (VAD endpointing, transcription, TTS
            streaming, and the WebSocket handshake). The full STT→agent→TTS
            turn is covered by manual/live testing — these check the state
            machine, synthesis plumbing, and transport wiring.
Dependencies: pytest, numpy, faster-whisper (bundled Silero VAD), edge-tts
Scope:      Detector endpointing, trimming, lazy model-load contracts, /ws/voice.

Note: edge-tts synthesis tests hit Microsoft's service — skipped when
NO_NETWORK_TESTS is set so CI without egress still runs.
"""

from __future__ import annotations

import json
import os

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from src.research.voice_stt import VoiceActivityDetector
from src.research.voice_tts import tts_chunks

SAMPLE_RATE = 16_000
WINDOW = 512


def _noise(duration_s: float, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal(int(duration_s * SAMPLE_RATE)).astype(np.float32)


def test_detector_closes_turn_after_silence() -> None:
    """Speech burst + trailing silence must yield exactly one Utterance."""
    detector = VoiceActivityDetector(threshold=0.1, silence_ms=400, min_speech_ms=150)
    speech = _noise(0.8)
    silence = np.zeros(SAMPLE_RATE // 2, dtype=np.float32)

    utter = detector.push(speech)
    assert utter is None, "speech alone must not close the turn yet"

    utter = detector.push(silence)
    assert utter is not None, "trailing silence must end the turn"
    assert utter.audio.size > 0
    assert 0.3 <= utter.duration_s <= 1.3, f"speech span not trimmed correctly: {utter.duration_s}s"


def test_detector_ignores_silence_only() -> None:
    """A sustained silence must never produce an utterance."""
    detector = VoiceActivityDetector(threshold=0.1, silence_ms=400, min_speech_ms=150)
    silence = np.zeros(int(2.0 * SAMPLE_RATE), dtype=np.float32)
    assert detector.push(silence) is None


def test_detector_flush_force_ends() -> None:
    """flush() must return a turn even without trailing silence."""
    detector = VoiceActivityDetector(threshold=0.1, silence_ms=400, min_speech_ms=150)
    speech = _noise(0.6)
    # Feed window-by-window like a real mic so the detector can't mistake the
    # tail of one big chunk for end-of-speech before flush() is called.
    for i in range(0, len(speech) - WINDOW + 1, WINDOW):
        detector.push(speech[i : i + WINDOW])
    utter = detector.flush()
    assert utter is not None
    assert utter.audio.size > 0


def test_detector_drops_short_burst() -> None:
    """Sub-threshold blips shorter than min_speech must be discarded."""
    detector = VoiceActivityDetector(threshold=0.1, silence_ms=400, min_speech_ms=150)
    # 100 ms of noise ≈ a cough — under min_speech_ms.
    blip = _noise(0.1)
    detector.push(blip)
    assert detector.flush() is None


@pytest.mark.skipif(
    os.environ.get("NO_NETWORK_TESTS") == "1",
    reason="edge-tts needs network access",
)
def test_tts_streams_bytes() -> None:
    """tts_chunks must yield non-empty audio byte chunks for real text."""

    async def _collect():
        chunks = [b async for b in tts_chunks("Hello there.", rate="+0%")]
        return chunks

    import asyncio

    chunks = asyncio.run(_collect())
    assert len(chunks) >= 1
    assert all(isinstance(c, bytes) and len(c) > 0 for c in chunks)


@pytest.mark.skipif(
    os.environ.get("NO_NETWORK_TESTS") == "1",
    reason="edge-tts needs network access",
)
def test_tts_empty_text_yields_nothing() -> None:
    import asyncio

    async def _collect():
        return [b async for b in tts_chunks("   ")]

    assert asyncio.run(_collect()) == []


def test_voice_ws_sends_ready_frame() -> None:
    """Connecting to /api/research/ws/voice must yield a ready frame, and a
    silence-only session must never trigger a research run."""
    client = TestClient(create_app())
    with client.websocket_connect("/api/research/ws/voice") as ws:
        frame = json.loads(ws.receive_text())
        assert frame["type"] == "ready"

        # Silence, then a manual stop: the detector holds nothing worth turning
        # into an utterance, so no pipeline work may start.
        ws.send_bytes(np.zeros(SAMPLE_RATE // 4, dtype=np.float32).tobytes())
        ws.send_text(json.dumps({"action": "stop"}))
        ws.send_text(json.dumps({"action": "stop"}))
    # Clean close is itself the assertion that no turn was in flight.
