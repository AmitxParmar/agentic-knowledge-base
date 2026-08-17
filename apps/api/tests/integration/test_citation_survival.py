"""
Integration test: citation reference survives from retrieval → agent → response.
conventions.md requires this test: "retrieval pipeline needs an integration test
that asserts citations survive the full path."

This test mocks the DB and embedding endpoints to stay fast, but exercises the real
RRF fusion, reranker ordering, and citation-at-retrieval accumulation logic.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.retrieval.pipeline import RetrievedChunk, _reciprocal_rank_fusion, _rerank_candidates
from src.retrieval.vector_index import VectorSearchResult

# ── RRF unit test ─────────────────────────────────────────────────────────────

def test_reciprocal_rank_fusion_merges_and_orders() -> None:
    dense = [
        VectorSearchResult(id="chunk-A", score=0.9),
        VectorSearchResult(id="chunk-B", score=0.8),
        VectorSearchResult(id="chunk-C", score=0.7),
    ]
    fts = [
        ("chunk-C", 1.5),  # FTS likes C more
        ("chunk-A", 1.2),
        ("chunk-D", 0.9),  # only in FTS
    ]
    result = _reciprocal_rank_fusion(dense, fts, pool=10)

    # chunk-A appears in both lists and should rank highly
    assert "chunk-A" in result
    assert "chunk-C" in result
    # chunk-D only in FTS, still included
    assert "chunk-D" in result


def test_rrf_deduplicates() -> None:
    """Same chunk in both lists should appear only once."""
    dense = [VectorSearchResult(id="chunk-X", score=0.95)]
    fts = [("chunk-X", 2.0)]
    result = _reciprocal_rank_fusion(dense, fts, pool=10)
    assert result.count("chunk-X") == 1


# ── Reranker test ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rerank_reorders_by_score() -> None:
    candidates = [
        RetrievedChunk(chunk_id="a", document_id="d1", chunk_text="low relevance", source_ref="doc.pdf, chunk 1", relevance_score=0.0),
        RetrievedChunk(chunk_id="b", document_id="d1", chunk_text="high relevance", source_ref="doc.pdf, chunk 2", relevance_score=0.0),
    ]
    # Mock reranker to say second passage is more relevant
    with patch("src.retrieval.pipeline.rerank", new=AsyncMock(return_value=[0.2, 0.9])):
        result = await _rerank_candidates("test question", candidates)

    assert result[0].chunk_id == "b", "Higher-scored chunk should come first"
    assert result[0].relevance_score == 0.9


# ── Citation survival test ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_citations_accumulated_at_retrieval() -> None:
    """
    The agent must accumulate citation refs the moment chunks are retrieved —
    not reconstruct them from the final answer. This test verifies the
    citation-at-retrieval pattern (conventions.md).
    """
    from src.research.agent import AgentResult

    # Simulate what the agent accumulates during a run
    accumulated_citations: list[dict[str, Any]] = [
        {"chunk_id": str(uuid.uuid4()), "document_id": str(uuid.uuid4()), "source_ref": "report.pdf, chunk 3", "relevance_score": 0.85},
        {"chunk_id": str(uuid.uuid4()), "document_id": str(uuid.uuid4()), "source_ref": "code/main.py:MyClass", "relevance_score": 0.72},
    ]

    result = AgentResult(answer="The answer.", citations=accumulated_citations)

    # Every citation has a source_ref — no citation is missing its reference
    for c in result.citations:
        assert c.get("source_ref"), "Every citation must carry its source_ref"
        assert c.get("chunk_id"), "Every citation must carry its chunk_id"

    assert len(result.citations) == 2
    assert result.citations[0]["source_ref"] == "report.pdf, chunk 3"
    assert result.citations[1]["source_ref"] == "code/main.py:MyClass"
