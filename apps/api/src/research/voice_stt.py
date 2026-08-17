"""
research/voice_stt.py
---------------------
Purpose:    Real-time speech-to-text for the voice channel.
            Buffers PCM frames from the wire, runs Silero VAD to find the
            utterance boundary (endpointing), then transcribes the buffered
            utterance with faster-whisper.

Why not stream transcribe(): faster-whisper's transcribe() takes a complete
array, not incremental frames. The cheap fix is the correct one — VAD tells
us when the user stopped, then we decode the captured window once.

Design notes:
- Silero VAD model ships inside faster-whisper (silero_vad_v6.onnx, ONNX
  Runtime) — no new dependency, cached module-level.
- VAD probability is recomputed over the full buffer each time a new 512-
  sample window lands (model state resets per call). The model is stateless,
  so growing the buffer by a window each time is consistent but ~O(n²) in
  utterance length. Fine at these sizes (utterance capped by
  VOICE_VAD_MAX_SPEECH_MS); per-window incremental VAD state is the upgrade
  path if a deployment transcribes a longer tail.
- `small` model (int8, CPU) is the latency default; swap via VOICE_STT_MODEL.
Scope:      Detection + transcription only. No transport, no agent wiring.

Run self-check:  python -m src.research.voice_stt
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.settings import settings

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
WINDOW = 512  # samples per VAD frame (~32 ms @ 16 kHz)
SECONDS_PER_WINDOW = WINDOW / SAMPLE_RATE

# ~400 ms pad each side of the speech span before Whisper decodes, mirroring
# faster-whisper's speech_pad_ms default so the model has context.
_PAD_WINDOWS = 12


@dataclass
class Utterance:
    audio: np.ndarray  # mono float32 16 kHz, speech span + pad
    duration_s: float
    start_offset_s: float = 0.0


class VoiceActivityDetector:
    """
    Streaming endpointing state machine. Feed PCM chunks via push();
    it returns a complete Utterance when trailing silence closes the turn.
    """

    def __init__(
        self,
        *,
        threshold: float = settings.VOICE_VAD_THRESHOLD,
        silence_ms: int = settings.VOICE_VAD_SILENCE_MS,
        min_speech_ms: int = settings.VOICE_VAD_MIN_SPEECH_MS,
        max_speech_ms: int = settings.VOICE_VAD_MAX_SPEECH_MS,
    ) -> None:
        self._threshold = threshold
        self._silence_windows = max(1, int(silence_ms / 1000 / SECONDS_PER_WINDOW))
        self._min_speech_windows = max(1, int(min_speech_ms / 1000 / SECONDS_PER_WINDOW))
        self._max_speech_windows = max(1, int(max_speech_ms / 1000 / SECONDS_PER_WINDOW))

        self._vad = _get_vad_model()
        self._reset()

    def _reset(self) -> None:
        self._buffer: list[np.ndarray] = []
        self._total_samples = 0
        self._speech_seen = False
        self._turned_at = time.monotonic()

    def push(self, chunk: np.ndarray) -> Utterance | None:
        """Feed raw samples; returns a completed Utterance when a turn ends."""
        if chunk.size == 0:
            return None

        # Cap runaway buffers even if the user never pauses.
        if self._total_samples + chunk.size >= self._max_speech_windows * WINDOW:
            return self._finish(force=True)

        self._buffer.append(chunk)
        self._total_samples += chunk.size
        if self._total_samples < WINDOW:
            return None

        audio, _ = self._as_speech_span(want_probs=False)
        probs = self._probs_for(audio)
        if not probs.size:
            return None

        voiced = probs > self._threshold
        # Number of trailing windows below threshold — the speech-end signal.
        trailing_silence = int(np.argmax(voiced[::-1]))

        self._speech_seen = self._speech_seen or bool(voiced.any())

        if self._speech_seen and trailing_silence >= self._silence_windows:
            return self._finish()

        if probs.size >= self._max_speech_windows:
            # Won't fit in the cap even if pad-sliced — stop now.
            return self._finish(force=True)

        # Long pre-roll silence without any speech yet: roll it off so the
        # buffer doesn't grow unbounded while waiting for the user to talk.
        if not self._speech_seen and probs.size >= self._silence_windows * 4:
            self._buffer = self._buffer[-len(self._buffer) // 2 :]
            self._total_samples = sum(b.size for b in self._buffer)

        return None

    def flush(self) -> Utterance | None:
        """Force-end any in-progress turn (manual stop / disconnect)."""
        return self._finish() if self._speech_seen else None

    def _finish(self, *, force: bool = False) -> Utterance | None:
        audio, probs = self._as_speech_span(want_probs=True)
        if probs is not None:
            # Count voiced windows. Trailing silence windows are below the
            # threshold anyway, so they contribute nothing — no need to slice
            # the tail off before counting.
            n_speech = int(np.sum(probs > self._threshold))
        else:
            n_speech = self._min_speech_windows if self._speech_seen else 0

        if n_speech < self._min_speech_windows and not force:
            self._reset()
            return None
        if audio.size == 0:
            self._reset()
            return None

        audio = self.slice_speech_span(audio, probs)
        utterance = Utterance(
            audio=np.ascontiguousarray(audio, dtype=np.float32),
            duration_s=round(audio.size / SAMPLE_RATE, 3),
            start_offset_s=round(time.monotonic() - self._turned_at, 3),
        )
        self._reset()
        return utterance

    def _as_speech_span(self, *, want_probs: bool):
        """Concatenate the buffer and (optionally) compute VAD probabilities."""
        audio = np.concatenate(self._buffer).astype(np.float32)
        if not want_probs:
            return audio, None
        return audio, self._probs_for(audio)

    def _probs_for(self, audio: np.ndarray) -> np.ndarray:
        """Silero speech probability per 512-sample window over the buffer."""
        n = audio.size // WINDOW
        if n == 0:
            return np.array([], dtype=np.float32)
        full = audio[: n * WINDOW]
        # VAD input must be exactly shaped; recompute over the whole buffer
        # each call so the (stateless) model sees consistent context.
        try:
            probs = self._vad(full).flatten()
        except Exception as exc:
            logger.warning("voice_stt: VAD inference failed (%s)", exc)
            return np.array([], dtype=np.float32)
        return probs.astype(np.float32)

    def slice_speech_span(self, audio: np.ndarray, probs: np.ndarray | None = None) -> np.ndarray:
        """Trim leading/trailing silence, keeping a ~400 ms pad each side."""
        if probs is None:
            probs = self._probs_for(audio)
        if probs.size == 0:
            return audio
        voiced = np.flatnonzero(probs > self._threshold)
        if voiced.size == 0:
            return audio
        first = max(0, voiced[0] - _PAD_WINDOWS)
        last = min(audio.size // WINDOW - 1, voiced[-1] + _PAD_WINDOWS)
        return audio[first * WINDOW : (last + 1) * WINDOW]


# ── faster-whisper transcription ──────────────────────────────────────────────

_model_lock = threading.Lock()
_whisper_model: Any = None


def _get_whisper_model() -> Any:
    """Lazily load the faster-whisper model (int8 CPU) once and cache it."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    # Imported lazily so optional deps stay optional for tests/lint.
    from faster_whisper import WhisperModel  # type: ignore[import-untyped]

    with _model_lock:
        if _whisper_model is None:
            logger.info("voice_stt: loading faster-whisper model=%s", settings.VOICE_STT_MODEL)
            _whisper_model = WhisperModel(
                settings.VOICE_STT_MODEL,
                device=settings.VOICE_DEVICE,
                compute_type="int8",
                cpu_threads=settings.VOICE_CPU_THREADS,
            )
    return _whisper_model


def _transcribe_blocking(audio: np.ndarray) -> str:
    """Run faster-whisper on a full utterance in a worker thread."""
    model = _get_whisper_model()
    # vad_filter=False: the utterance is already a tight speech span from VAD;
    # re-running Whisper's VAD would waste the latency budget.
    segments, _ = model.transcribe(audio, beam_size=1, vad_filter=False)
    return " ".join(seg.text.strip() for seg in segments).strip()


async def transcribe_utterance(utterance: Utterance) -> str:
    """Transcribe a captured utterance off the event loop."""
    if utterance.duration_s < 0.2:
        return ""
    text = await asyncio.wait_for(
        asyncio.to_thread(_transcribe_blocking, utterance.audio),
        timeout=settings.VOICE_STT_TIMEOUT,
    )
    return text


# ── Silero VAD model ──────────────────────────────────────────────────────────

_vad_lock = threading.Lock()
_vad_model: Any = None


def _get_vad_model() -> Any:
    """Cached Silero VAD model bundled with faster-whisper."""
    global _vad_model
    if _vad_model is not None:
        return _vad_model
    from faster_whisper.vad import get_vad_model

    with _vad_lock:
        if _vad_model is None:
            _vad_model = get_vad_model()
    return _vad_model


# ── Self-check (ponytail: leave one runnable check) ───────────────────────────


async def _demo() -> None:
    """
    Verify the endpointing state machine end-to-end: a "speech" burst (white
    noise — Silero's strongest synthetic trigger) followed by silence must
    yield one Utterance, fed window-by-window like a real mic.
    Threshold lowered below 0.5 because deterministic synthetic signals never
    hit the 0.5 a real voice does — this checks *our* logic (buffer /
    trailing-silence / trim), not the third-party VAD model.
    """
    import sys

    rng = np.random.default_rng(42)
    speech = rng.standard_normal(int(0.8 * SAMPLE_RATE)).astype(np.float32)
    silence = np.zeros(SAMPLE_RATE // 2, dtype=np.float32)

    detector = VoiceActivityDetector(threshold=0.1, silence_ms=400, min_speech_ms=150)
    utterance: Utterance | None = None
    for chunk in list(_windows(speech)) + list(_windows(silence)):
        utterance = detector.push(chunk)
        if utterance is not None:
            break

    assert utterance is not None, "expected an uttered turn (empty)"
    print(f"detected utterance: duration={utterance.duration_s}s, samples={utterance.audio.size}")
    assert utterance.audio.size > 0, "utterance audio is empty"
    assert utterance.duration_s >= 0.3, f"utterance too short: {utterance.duration_s}s"
    # Slicing must have trimmed the trailing 0.5 s of silence.
    assert utterance.duration_s < 1.3, (
        f"speech span was not trimmed: {utterance.duration_s}s (expected ~0.8s + pad)"
    )
    print("voice_stt self-check OK")
    sys.exit(0)


def _windows(audio: np.ndarray) -> list[np.ndarray]:
    """Split audio into 512-sample chunks, mirroring the mic frame size."""
    n = audio.size // WINDOW
    return [audio[i * WINDOW : (i + 1) * WINDOW] for i in range(n)]


if __name__ == "__main__":
    asyncio.run(_demo())
