"""
tests/retrieval/test_parent_context.py
--------------------------------------
Parent-context expansion (retrieval.md): adjacent-sibling text merged
into a selected chunk's own citation block, sentence-bounded. The DB is
faked with a two-response AsyncSession stand-in.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from src.retrieval.pipeline import (
    _CONTEXT_MAX_CHARS,
    RetrievedChunk,
    _attach_parent_context,
    _truncate_at_sentence_boundary,
)

DOC = uuid.UUID(int=1)


# ── sentence-bounded truncation ───────────────────────────────────────────────


def test_truncate_short_text_untouched() -> None:
    assert _truncate_at_sentence_boundary("Short text.", remaining=100) == "Short text."


def test_truncate_zero_remaining_is_empty() -> None:
    assert _truncate_at_sentence_boundary("Anything.", remaining=0) == ""


def test_truncate_cuts_at_sentence_boundary() -> None:
    text = "First sentence here. Second sentence follows it. Third one is much longer."
    cut = _truncate_at_sentence_boundary(text, remaining=60)
    assert len(cut) <= 60
    assert cut.endswith(".")
    assert cut == "First sentence here. Second sentence follows it."


def test_truncate_without_boundary_cuts_at_word() -> None:
    cut = _truncate_at_sentence_boundary("word " * 60, remaining=50)
    assert len(cut) <= 50
    assert not cut.endswith(" ")


# ── attach_parent_context ─────────────────────────────────────────────────────


class FakeChunkRow:
    def __init__(self, position: int, text: str) -> None:
        self.document_id = DOC
        self.position = position
        self.text = text


def _session_with(positions: list[tuple[uuid.UUID, int]], chunk_rows: list[Any]) -> MagicMock:
    """AsyncSession stand-in: first execute returns (doc, pos) tuples,
    second returns Chunk-like rows."""
    session = MagicMock()
    responses = [positions, chunk_rows]
    calls = {"i": 0}

    async def execute(*args: object, **kwargs: object) -> MagicMock:
        result = MagicMock()
        result.all.return_value = responses[min(calls["i"], 1)]
        calls["i"] += 1
        return result

    session.execute = AsyncMock(side_effect=execute)  # type: ignore[assignment]
    return session


def _selected(position: int = 3) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=str(uuid.uuid4()),
        document_id=str(DOC),
        chunk_text="The refund window is thirty days.",
        source_ref="policy.pdf, chunk 3",
        relevance_score=0.9,
        position=position,
    )


async def test_no_selected_chunks_skips_db() -> None:
    session = MagicMock()
    await _attach_parent_context([], session)  # type: ignore[arg-type]
    session.execute.assert_not_called()


async def test_neighbors_merged_own_text_excluded() -> None:
    prev_text = "Earlier section sets the policy background."
    next_text = "The following section covers EU exceptions."
    session = _session_with(
        positions=[(DOC, p) for p in (2, 3, 4)],
        chunk_rows=[
            FakeChunkRow(2, prev_text),
            FakeChunkRow(3, "The refund window is thirty days."),  # own row - skipped
            FakeChunkRow(4, next_text),
        ],
    )

    chunk = _selected(position=3)
    await _attach_parent_context([chunk], session)  # type: ignore[arg-type]

    assert prev_text in chunk.context_text
    assert next_text in chunk.context_text
    assert "refund window" not in chunk.context_text  # own body never duplicated


async def test_missing_neighbors_yield_empty_context() -> None:
    # Only the hit's own position exists - no siblings to attach.
    session = _session_with(
        positions=[(DOC, 3)],
        chunk_rows=[FakeChunkRow(3, "only self")],
    )
    chunk = _selected(position=3)
    await _attach_parent_context([chunk], session)  # type: ignore[arg-type]
    assert chunk.context_text == ""


async def test_existing_context_not_overwritten() -> None:
    session = _session_with(
        positions=[(DOC, 2), (DOC, 3), (DOC, 4)],
        chunk_rows=[FakeChunkRow(2, "prev"), FakeChunkRow(4, "next")],
    )
    chunk = _selected()
    chunk.context_text = "kept as-is"
    await _attach_parent_context([chunk], session)  # type: ignore[arg-type]
    assert chunk.context_text == "kept as-is"


async def test_db_failure_degrades_silently() -> None:
    session = MagicMock()
    session.execute = AsyncMock(side_effect=RuntimeError("db down"))  # type: ignore[assignment]
    chunk = _selected()
    await _attach_parent_context([chunk], session)  # type: ignore[arg-type]
    assert chunk.context_text == ""
    assert chunk.chunk_text == "The refund window is thirty days."


async def test_total_context_bounded_by_budget() -> None:
    big = "A sentence of moderate length. " * 100  # ~3100 chars per sibling
    session = _session_with(
        positions=[(DOC, p) for p in (2, 3, 4)],
        chunk_rows=[FakeChunkRow(2, big), FakeChunkRow(4, big)],
    )
    chunk = _selected(position=3)
    await _attach_parent_context([chunk], session)  # type: ignore[arg-type]

    assert len(chunk.context_text) <= _CONTEXT_MAX_CHARS + len("\n...\n")
    assert chunk.context_text.count("...") >= 1  # neighbors separated by ellipsis marker