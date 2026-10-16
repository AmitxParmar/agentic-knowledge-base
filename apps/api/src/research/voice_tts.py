"""
research/voice_tts.py
---------------------
Purpose:    Turn a final research answer into speakable WAV chunks for the
            voice channel. Synthesis runs on the hosted Groq Orpheus model
            (`canopylabs/orpheus-v1-english`) through the Model Gateway —
            zero local inference (production runs on Render's 512 MB free
            tier) and no new API keys (ADR-006, amended 2026-10-16).

            The provider caps one request at 200 characters, so answers are
            sentence-chunked: each piece is synthesized to a complete WAV
            that the browser's `AudioContext.decodeAudioData()` plays
            natively. The caller streams chunk N while chunk N+1 synthesizes,
            so playback pipelines with synthesis (perceived-latency win).

Scope:      Synthesis only — no transport, no agent wiring. `tts_chunks` is
            the swap seam for future provider changes.

Run sanity check:  python -m src.research.voice_tts --text "Hello world"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from collections.abc import AsyncIterator

from src.shared.model_gateway import speech

logger = logging.getLogger(__name__)

# Groq Orpheus rejects inputs over 200 characters — stay just under so
# punctuation/whitespace never pushes a piece past the cap.
MAX_TTS_CHARS = 200


def _text_ok(text: str) -> bool:
    return bool(text.strip())


def _pack_words(text: str, *, max_chars: int) -> list[str]:
    """Greedily pack words into pieces ≤ max_chars; hard-slices a single
    token longer than the cap (URLs, hashes) so the request never overflows."""
    pieces: list[str] = []
    current = ""
    for word in text.split(" "):
        if len(word) > max_chars:
            # Flush what we have, then slice the oversized token itself.
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(word[i : i + max_chars] for i in range(0, len(word), max_chars))
            continue
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= max_chars:
            current = candidate
        else:
            pieces.append(current)
            current = word
    if current:
        pieces.append(current)
    return pieces


def _split_segment(segment: str, *, max_chars: int) -> list[str]:
    """Split one sentence over the cap on clause boundaries, then words."""
    if len(segment) <= max_chars:
        return [segment]
    pieces: list[str] = []
    for clause in re.split(r"(?<=[,;:\u2014\u2013]) ", segment):
        if len(clause) <= max_chars:
            pieces.append(clause)
        else:
            pieces.extend(_pack_words(clause, max_chars=max_chars))
    return pieces


def split_for_tts(text: str, *, max_chars: int = MAX_TTS_CHARS) -> list[str]:
    """
    Split `text` into speakable pieces of at most `max_chars` characters.

    Preference order: sentence boundaries → clause boundaries → word
    boundaries; pieces are greedily re-merged so short sentences travel in
    as few provider requests as possible (the free tier caps requests/day).
    """
    # Step 1: normalize whitespace (answers may carry newlines from the
    # model); nothing to speak for empty/whitespace-only input.
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []

    # Step 2: split into sentence-ish segments (punctuation + space; decimal
    # points ride along because they have no trailing space).
    segments = re.split(r"(?<=[.!?…]) ", normalized)

    # Step 3: bring every segment under the cap.
    pieces: list[str] = []
    for segment in segments:
        pieces.extend(_split_segment(segment, max_chars=max_chars))

    # Step 4: greedy re-merge adjacent pieces to minimize request count.
    merged: list[str] = []
    for piece in pieces:
        if merged and len(merged[-1]) + 1 + len(piece) <= max_chars:
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)
    return [p for p in merged if p.strip()]


async def tts_chunks(text: str, *, voice: str | None = None) -> AsyncIterator[bytes]:
    """
    Yield one WAV byte-blob per sentence-chunk of `text`, in order.

    Synthesis is sequential (request N+1 starts once N's bytes are yielded):
    the caller sends chunk N over the socket while the client plays it, so
    playback overlaps the synthesis of N+1. Exceptions surface to the
    caller — the voice router treats them as "fall back to text-only answer".
    """
    if not _text_ok(text):
        return

    for piece in split_for_tts(text):
        wav = await speech(piece, voice=voice)
        if wav:
            yield wav


async def _demo(text: str, voice: str | None = None) -> None:
    import sys

    if not _text_ok(text):
        print("empty text — nothing to synthesize")
        sys.exit(0)

    pieces = split_for_tts(text)
    print(f"split into {len(pieces)} piece(s): {[len(p) for p in pieces]} chars")

    total = 0
    n = 0
    async for chunk in tts_chunks(text, voice=voice):
        total += len(chunk)
        n += 1
    assert total > 0, "expected some audio, got none"
    print(f"synthesized {text!r}: {n} chunk(s), {total} bytes")
    sys.exit(0)


if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(level=_logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="Hello from the research terminal.")
    parser.add_argument("--voice", default=None)
    args = parser.parse_args()
    asyncio.run(_demo(args.text, args.voice))
