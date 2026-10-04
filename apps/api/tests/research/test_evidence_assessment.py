"""
tests/research/test_evidence_assessment.py
------------------------------------------
Purpose:    Verify the missing-information detection and context packing that
            guard against answering without grounded evidence and against
            context-window overflow. Covers _assess_evidence, _mean_relevance,
            _pack_chunks_for_model, and the zero-evidence hard refusal in
            run_agent.

Dependencies: pytest, src.research.agent, src.retrieval.pipeline
Scope:      Evidence-confidence + packing logic only — no model or DB calls.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.research.agent import (
    _INSUFFICIENT_EVIDENCE_RESPONSE,
    AgentResult,
    _assess_evidence,
    _estimate_tokens,
    _locate_in_answer,
    _make_probe,
    _mean_relevance,
    _pack_chunks_for_model,
    run_agent,
)
from src.retrieval.pipeline import _MAX_CHUNKS_PER_DOCUMENT, RetrievedChunk, _dedup_and_select

# ── _mean_relevance ───────────────────────────────────────────────────────────


def test_mean_relevance_empty_is_zero() -> None:
    assert _mean_relevance([]) == 0.0


def test_mean_relevance_averages_scores() -> None:
    citations = [
        {"relevance_score": 0.8},
        {"relevance_score": 0.4},
    ]
    assert _mean_relevance(citations) == pytest.approx(0.6)


def test_mean_relevance_treats_missing_score_as_zero() -> None:
    citations = [
        {"relevance_score": 0.9},
        {"relevance_score": None},
    ]
    assert _mean_relevance(citations) == pytest.approx(0.45)


# ── _assess_evidence ──────────────────────────────────────────────────────────


def test_assess_evidence_no_citations_is_insufficient() -> None:
    assert _assess_evidence([]) == "insufficient"


def test_assess_evidence_strong_mean_is_sufficient() -> None:
    citations = [{"relevance_score": 0.9}, {"relevance_score": 0.7}]
    assert _assess_evidence(citations) == "sufficient"


def test_assess_evidence_weak_mean_is_insufficient() -> None:
    # Mean 0.1, below the 0.2 threshold — tangential matches.
    citations = [{"relevance_score": 0.12}, {"relevance_score": 0.08}]
    assert _assess_evidence(citations) == "insufficient"


def test_assess_evidence_mixed_but_mean_above_threshold() -> None:
    # One weak, one strong — mean 0.5 clears the bar.
    citations = [{"relevance_score": 0.1}, {"relevance_score": 0.9}]
    assert _assess_evidence(citations) == "sufficient"


# ── run_agent zero-evidence refusal ───────────────────────────────────────────


def _make_final_state(
    *,
    citations: list[dict[str, Any]],
    answer: str = "Some answer from the model.",
    iterations: int = 1,
    tokens_used: int = 100,
) -> dict[str, Any]:
    return {
        "run_id": str(uuid.uuid4()),
        "workspace_id": str(uuid.uuid4()),
        "question": "test",
        "messages": [],
        "citations": citations,
        "answer": answer,
        "iterations": iterations,
        "tokens_used": tokens_used,
    }


@pytest.mark.asyncio
async def test_run_agent_refuses_when_no_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero citations must force the hard refusal, not the model's answer."""
    final_state = _make_final_state(citations=[])

    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(return_value=final_state)
    monkeypatch.setattr(
        "src.research.agent._get_graph",
        AsyncMock(return_value=mock_graph),
    )
    # Skip citation persistence — not what this test covers.
    monkeypatch.setattr(
        "src.research.agent._persist_citations",
        AsyncMock(),
    )

    result = await run_agent(
        question="What does the report say?",
        workspace_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        session=AsyncMock(),
    )

    assert result.confidence == "insufficient"
    assert result.answer == _INSUFFICIENT_EVIDENCE_RESPONSE


@pytest.mark.asyncio
async def test_run_agent_keeps_answer_when_evidence_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Citations present + strong mean → model answer preserved, sufficient."""
    citations = [
        {
            "chunk_id": str(uuid.uuid4()),
            "document_id": str(uuid.uuid4()),
            "source_ref": "report.pdf, chunk 1",
            "relevance_score": 0.85,
        }
    ]
    final_state = _make_final_state(citations=citations, answer="The capital is Paris.")

    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(return_value=final_state)
    monkeypatch.setattr(
        "src.research.agent._get_graph",
        AsyncMock(return_value=mock_graph),
    )
    monkeypatch.setattr(
        "src.research.agent._persist_citations",
        AsyncMock(),
    )

    result = await run_agent(
        question="What is the capital?",
        workspace_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        session=AsyncMock(),
    )

    assert result.confidence == "sufficient"
    assert result.answer == "The capital is Paris."


def test_agent_result_defaults_to_sufficient() -> None:
    """AgentResult.confidence must default to sufficient for backward compat."""
    result = AgentResult(answer="ok")
    assert result.confidence == "sufficient"


# ── _estimate_tokens ──────────────────────────────────────────────────────────


def test_estimate_tokens_scales_with_length() -> None:
    assert _estimate_tokens("abcd") == 1
    assert _estimate_tokens("x" * 400) == 100


def test_estimate_tokens_minimum_is_one() -> None:
    assert _estimate_tokens("") == 1


# ── _pack_chunks_for_model ────────────────────────────────────────────────────


def _make_chunks(count: int, *, text_len: int = 100) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=str(uuid.uuid4()),
            document_id=str(uuid.uuid4()),
            chunk_text="t" * text_len,
            source_ref=f"file_{i}.pdf, chunk {i}",
            relevance_score=0.9 - (i * 0.01),
            position=i,
        )
        for i in range(count)
    ]


def test_pack_empty_returns_no_documents_message() -> None:
    assert _pack_chunks_for_model([]) == "No relevant documents found for this query."


def test_pack_fits_all_chunks_under_budget() -> None:
    chunks = _make_chunks(2, text_len=100)  # well under 3000-token budget
    packed = _pack_chunks_for_model(chunks)

    assert "[1] Source: file_0.pdf, chunk 0" in packed
    assert "[2] Source: file_1.pdf, chunk 1" in packed
    assert "tttt" in packed


def test_pack_drops_low_relevance_tail_over_budget() -> None:
    # 8 chunks of 512 tokens (~2048 chars) each ≈ 4096 tokens total, over budget.
    chunks = _make_chunks(8, text_len=2048)
    packed = _pack_chunks_for_model(chunks)

    # Highest-relevance chunk always included.
    assert "[1] Source: file_0.pdf, chunk 0" in packed
    # The least-relevance chunk should be dropped to stay under budget.
    assert "[8] Source: file_7.pdf, chunk 7" not in packed


def test_pack_preserves_citation_index_alignment() -> None:
    """Packed [n] markers must align with the original chunk (citation) order."""
    chunks = _make_chunks(3, text_len=100)
    packed = _pack_chunks_for_model(chunks)

    # All three fit, numbered 1:1 with their citation positions.
    assert "[1] Source: file_0.pdf, chunk 0" in packed
    assert "[2] Source: file_1.pdf, chunk 1" in packed
    assert "[3] Source: file_2.pdf, chunk 2" in packed


def test_pack_truncates_last_chunk_with_ellipsis() -> None:
    # First chunk ~1500 tokens (fits), second ~2500 tokens — combined over the
    # 3000-token budget, so the second must be truncated with an ellipsis.
    chunks = [
        RetrievedChunk(str(uuid.uuid4()), str(uuid.uuid4()), "a" * 6000, "big_0.pdf, chunk 0", 0.9, 0),
        RetrievedChunk(str(uuid.uuid4()), str(uuid.uuid4()), "b" * 10000, "big_1.pdf, chunk 1", 0.8, 1),
    ]
    packed = _pack_chunks_for_model(chunks)

    assert "big_0.pdf, chunk 0" in packed
    assert "big_1.pdf, chunk 1" in packed
    assert "...\n</document>" in packed  # truncated body, delimiters still closed


def test_pack_stays_within_token_budget() -> None:
    """Packed output must not exceed the configured budget (in tokens)."""
    chunks = _make_chunks(8, text_len=2048)
    packed = _pack_chunks_for_model(chunks)

    assert _estimate_tokens(packed) <= 3000 + 50  # +50 for header overhead per block


# ── _dedup_and_select (Phase 3: evidence dedup + diversity) ───────────────────


def _ranked_chunks(specs: list[tuple[str, int, float]]) -> list[RetrievedChunk]:
    """Build a pre-ranked chunk list from (document_id, position, score) tuples."""
    return [
        RetrievedChunk(
            chunk_id=str(uuid.uuid4()),
            document_id=doc_id,
            chunk_text=f"text-{doc_id}-{pos}",
            source_ref=f"{doc_id}, chunk {pos}",
            relevance_score=score,
            position=pos,
        )
        for doc_id, pos, score in specs
    ]


def test_dedup_drops_adjacent_positions_same_document() -> None:
    # Same document at positions 3 and 4 — overlapping, near-duplicate. The
    # higher-ranked (3, score 0.9) stays; (4, 0.85) is dropped.
    ranked = _ranked_chunks([("doc-a", 3, 0.9), ("doc-a", 4, 0.85), ("doc-b", 1, 0.7)])
    selected = _dedup_and_select(ranked, top_k=3)

    assert len(selected) == 2
    assert selected[0].position == 3
    assert selected[1].document_id == "doc-b"


def test_dedup_keeps_non_adjacent_same_document() -> None:
    # Positions 1 and 5 are not overlapping — both may stay.
    ranked = _ranked_chunks([("doc-a", 1, 0.9), ("doc-a", 5, 0.8)])
    selected = _dedup_and_select(ranked, top_k=3)

    assert len(selected) == 2
    assert {c.position for c in selected} == {1, 5}


def test_dedup_caps_chunks_per_document() -> None:
    # doc-a has 5 well-spaced chunks; cap limits it to _MAX_CHUNKS_PER_DOCUMENT.
    ranked = _ranked_chunks([
        ("doc-a", 1, 0.95),
        ("doc-a", 5, 0.9),
        ("doc-a", 10, 0.85),
        ("doc-a", 15, 0.8),
        ("doc-a", 20, 0.75),
    ])
    selected = _dedup_and_select(ranked, top_k=8)

    doc_a_count = sum(1 for c in selected if c.document_id == "doc-a")
    assert doc_a_count == _MAX_CHUNKS_PER_DOCUMENT


def test_dedup_preserves_relevance_order() -> None:
    # Output must stay sorted by descending relevance regardless of dedup.
    ranked = _ranked_chunks([
        ("doc-a", 1, 0.9),
        ("doc-a", 2, 0.88),  # adjacent to pos 1 → dropped
        ("doc-b", 1, 0.85),
        ("doc-c", 1, 0.8),
    ])
    selected = _dedup_and_select(ranked, top_k=8)

    scores = [c.relevance_score for c in selected]
    assert scores == sorted(scores, reverse=True)
    assert [c.document_id for c in selected] == ["doc-a", "doc-b", "doc-c"]


def test_dedup_respects_top_k() -> None:
    ranked = _ranked_chunks([(f"doc-{i}", 1, 0.9 - i * 0.01) for i in range(10)])
    selected = _dedup_and_select(ranked, top_k=3)

    assert len(selected) == 3


def test_dedup_empty_input() -> None:
    assert _dedup_and_select([], top_k=8) == []


# ── _locate_in_answer / _make_probe (Phase 4: citation grounding) ─────────────


def test_make_probe_short_text_unchanged() -> None:
    assert _make_probe("hello world") == "hello world"


def test_make_probe_trims_long_text_at_word_boundary() -> None:
    text = "word " * 100  # well over 120 chars
    probe = _make_probe(text)
    assert len(probe) <= 120
    assert not probe.endswith(" "), "probe must not end mid-word"


def test_locate_finds_exact_chunk_text() -> None:
    answer = "The capital of France is Paris, known for the Eiffel Tower."
    chunk_text = "Paris, known for the Eiffel Tower"
    span = _locate_in_answer(chunk_text, answer)

    assert span is not None
    start, end = span
    assert answer[start:end].lower() == chunk_text.lower()


def test_locate_case_insensitive() -> None:
    answer = "The report states that revenue grew by fifteen percent."
    span = _locate_in_answer("REVENUE GREW", answer)

    assert span is not None


def test_locate_whitespace_tolerant() -> None:
    # Answer collapses/re-spaces the chunk text.
    answer = "Findings show revenue   grew   by 15 percent year over year."
    span = _locate_in_answer("revenue grew by 15 percent", answer)

    assert span is not None


def test_locate_returns_none_when_absent() -> None:
    answer = "The capital of France is Paris."
    assert _locate_in_answer("completely unrelated text not present", answer) is None


def test_locate_returns_none_on_empty_inputs() -> None:
    assert _locate_in_answer(None, "some answer") is None
    assert _locate_in_answer("text", None) is None
    assert _locate_in_answer("", "answer") is None


def test_locate_uses_probe_for_long_chunk() -> None:
    # Chunk longer than the probe still matches via its opening words.
    answer = "According to the study the quick brown fox jumped over the fence."
    chunk_text = "the quick brown fox jumped over the fence and ran into the forest"
    span = _locate_in_answer(chunk_text, answer)

    assert span is not None
    start, end = span
    assert answer[start:end] == "the quick brown fox jumped over the fence"
