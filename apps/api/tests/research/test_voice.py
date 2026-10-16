"""
tests/research/test_voice.py
-----------------------------
Purpose:    Tests for the voice channel (VAD endpointing, TTS chunking, and
            the WebSocket handshake). TTS synthesis runs on the hosted Groq
            Orpheus model (ADR-006 amendment) — these tests mock the Model
            Gateway so they run fully offline. The live probe is opt-in via
            LIVE_TTS_TESTS=1 (requires the Groq model terms to be accepted
            in the console once).
Dependencies: pytest, numpy, faster-whisper (bundled Silero VAD)
Scope:      Detector endpointing, chunk splitting, synthesis plumbing, /ws/voice.
"""

from __future__ import annotations

import asyncio
import json
import os

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from src.research.voice_stt import VoiceActivityDetector
from src.research.voice_tts import MAX_TTS_CHARS, split_for_tts, tts_chunks

SAMPLE_RATE = 16_000
WINDOW = 512
FAKE_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt "


def _noise(duration_s: float, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal(int(duration_s * SAMPLE_RATE)).astype(np.float32)


# ── VAD endpointing ───────────────────────────────────────────────────────────


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


# ── TTS chunking (offline) ────────────────────────────────────────────────────


def test_split_short_text_single_piece() -> None:
    assert split_for_tts("Hello there.") == ["Hello there."]


def test_split_empty_and_whitespace_yield_nothing() -> None:
    assert split_for_tts("") == []
    assert split_for_tts("   \n\t ") == []


def test_split_merges_short_sentences() -> None:
    """Short sentences must travel in as few provider requests as possible."""
    text = "Yes. No. Maybe. Certainly. Absolutely."
    assert split_for_tts(text) == [text]


def test_split_respects_cap_and_keeps_content() -> None:
    """Long answers split under the provider cap without dropping sentences."""
    text = " ".join(
        f"Sentence number {i} is a little longer than the average here." for i in range(20)
    )
    pieces = split_for_tts(text)
    assert len(pieces) > 1
    assert all(len(piece) <= MAX_TTS_CHARS for piece in pieces)
    rejoined = " ".join(pieces)
    for i in range(20):
        assert f"Sentence number {i} is" in rejoined


def test_split_hard_slices_oversized_token() -> None:
    """A single token over the cap (e.g. a URL) is hard-sliced, never sent
    as one oversized request."""
    token = "x" * 450
    pieces = split_for_tts(token)
    assert all(len(piece) <= MAX_TTS_CHARS for piece in pieces)
    assert sum(len(piece) for piece in pieces) == 450


@pytest.fixture()
def fake_speech(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str | None]]:
    """Swap the hosted synthesis for an offline recorder returning fake WAVs."""
    calls: list[dict[str, str | None]] = []

    async def _fake(text: str, *, voice: str | None = None, model: str | None = None) -> bytes:
        calls.append({"text": text, "voice": voice})
        return FAKE_WAV + text.encode()

    monkeypatch.setattr("src.research.voice_tts.speech", _fake)
    return calls


def test_tts_yields_one_wav_per_piece(fake_speech: list[dict[str, str | None]]) -> None:
    """tts_chunks must yield one non-empty WAV per piece, in order, with
    every provider request under the character cap."""
    text = " ".join(f"Point {i} covers a distinct part of the answer." for i in range(15))

    async def _collect():
        return [chunk async for chunk in tts_chunks(text)]

    chunks = asyncio.run(_collect())
    assert len(chunks) == len(fake_speech) >= 2
    assert all(chunk.startswith(b"RIFF") for chunk in chunks)
    assert all(len(call["text"] or "") <= MAX_TTS_CHARS for call in fake_speech)
    # Order is preserved: the first request carries the first sentence.
    assert (fake_speech[0]["text"] or "").startswith("Point 0")


def test_tts_empty_text_never_calls_provider(fake_speech: list[dict[str, str | None]]) -> None:
    async def _collect():
        return [chunk async for chunk in tts_chunks("   ")]

    assert asyncio.run(_collect()) == []
    assert fake_speech == []


# ── Live probe (opt-in) ───────────────────────────────────────────────────────


@pytest.mark.skipif(
    os.environ.get("LIVE_TTS_TESTS") != "1",
    reason="set LIVE_TTS_TESTS=1 (and accept Groq model terms) to run the live probe",
)
def test_tts_live_synthesizes_wav() -> None:
    """End-to-end synthesis against Groq — run manually after accepting the
    Orpheus model terms in the Groq console."""

    async def _collect():
        return [chunk async for chunk in tts_chunks("Hello from the research terminal.")]

    chunks = asyncio.run(_collect())
    assert chunks, "provider returned no audio"
    assert all(chunk[:4] == b"RIFF" for chunk in chunks)


# ── WebSocket handshake ───────────────────────────────────────────────────────


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
