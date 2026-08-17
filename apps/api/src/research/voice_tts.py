"""
research/voice_tts.py
---------------------
Purpose:    Stream text-to-speech audio for the voice channel using edge-tts.
            edge-tts calls Microsoft Edge's neural voices over HTTPS — free,
            no API key, and yields MP3 chunks as they are synthesized so the
            first audio byte reaches the client before a long answer finishes
            (perceived-latency win, ADR-006).
Scope:      Synthesis only — no transport, no agent wiring.

Run sanity check:  python -m src.research.voice_tts --text "Hello world"
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from app.settings import settings

logger = logging.getLogger(__name__)


def _text_ok(text: str) -> bool:
    return bool(text.strip())


async def stream_tts(text: str, *, voice: str | None = None) -> None:
    """
    Placeholder signature kept for symmetry with the module loader — the real
    generator below is `tts_chunks`. This never raises for empty/whitespace.
    """
    if not _text_ok(text):
        return None


async def tts_chunks(
    text: str,
    *,
    voice: str | None = None,
    rate: str | None = None,
):
    """
    Yield MP3 bytes for `text`, streaming as synthesized.

    Clips the very first byte that edge-tts sometimes emits (`Type` framing);
    yields only `audio` payloads. Exceptions surface to the caller — the
    router treats them as "fall back to text-only answer".
    """
    if not _text_ok(text):
        return

    import edge_tts

    voice = voice or settings.VOICE_TTS_VOICE
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate or "+0%")

    first = True
    async for chunk in communicate.stream():
        if chunk["type"] != "audio":
            continue
        # edge-tts leads with a 1-byte MPEG framing byte — drop it so browsers
        # can decodeAudioData the stream directly.
        data = chunk.get("data", b"")
        if first and data and data[:1] == b"\x00":
            data = data[1:]
        first = False
        if data:
            yield data


async def _demo(text: str) -> None:
    import sys

    if not _text_ok(text):
        print("empty text — nothing to synthesize")
        sys.exit(0)

    total = 0
    n = 0
    async for chunk in tts_chunks(text):
        total += len(chunk)
        n += 1
    assert total > 0, "expected some audio, got none"
    print(f"synthesized {text!r}: {n} chunks, {total} bytes")
    sys.exit(0)


if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(level=_logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="Hello from the research terminal.")
    args = parser.parse_args()
    asyncio.run(_demo(args.text))
