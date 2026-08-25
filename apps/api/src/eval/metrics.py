"""
eval/metrics.py
---------------
Pure metric functions for the offline eval harness.

Every function is deterministic and side-effect free: ranked lists in,
scores out. No I/O, no model calls — safe to unit test exhaustively and
safe to run in CI without provider credentials.

Conventions:
- ``ranked_ids`` is relevance-ordered (best first).
- ``relevant_ids`` is the ground-truth set of expected chunk ids.
- Relevance is binary: a retrieved chunk either is or isn't expected.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

_CITATION_MARKER = re.compile(r"\[(\d{1,2})\]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def recall_at_k(ranked_ids: Sequence[str], relevant_ids: set[str], k: int) -> float:
    """Fraction of relevant chunks found within the top k."""
    if not relevant_ids:
        return 0.0
    top = set(ranked_ids[:k])
    return len(top & relevant_ids) / len(relevant_ids)


def precision_at_k(ranked_ids: Sequence[str], relevant_ids: set[str], k: int) -> float:
    """Fraction of the top k that are relevant."""
    if k <= 0:
        return 0.0
    top = ranked_ids[:k]
    if not top:
        return 0.0
    return sum(1 for cid in top if cid in relevant_ids) / len(top)


def mrr(ranked_ids: Sequence[str], relevant_ids: set[str]) -> float:
    """Reciprocal rank of the first relevant hit; 0.0 on miss."""
    for rank, cid in enumerate(ranked_ids, start=1):
        if cid in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked_ids: Sequence[str], relevant_ids: set[str], k: int) -> float:
    """Normalized discounted cumulative gain with binary relevance.

    DCG  = Σ rel_i / log2(i + 1) over ranks i = 1..k
    IDCG = DCG of |relevant ∩ top-k| ideal hits packed at the top.
    """
    if not relevant_ids or k <= 0:
        return 0.0
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, cid in enumerate(ranked_ids[:k], start=1)
        if cid in relevant_ids
    )
    ideal_hits = min(len(relevant_ids), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg


def delta_ndcg_at_k(
    pre_ids: Sequence[str],
    post_ids: Sequence[str],
    relevant_ids: set[str],
    k: int,
) -> float:
    """nDCG change between two rankings of the same corpus.

    The rerank-effectiveness measure: positive means the post ranking
    (post-rerank) beats the pre ranking (fusion order). This turns the
    "Cohere rerank improves retrieval" claim into a number per query.
    """
    return ndcg_at_k(post_ids, relevant_ids, k) - ndcg_at_k(pre_ids, relevant_ids, k)


def citation_coverage(answer: str, n_citations: int) -> float:
    """Fraction of provided citations actually referenced as [n] markers.

    A cached/rendered answer that carries citations but never marks them
    wastes them — coverage catches that drift.
    """
    if n_citations <= 0:
        return 1.0
    markers = {int(m) for m in _CITATION_MARKER.findall(answer)}
    hits = sum(1 for n in range(1, n_citations + 1) if n in markers)
    return hits / n_citations


def ungrounded_sentence_ratio(answer: str) -> float:
    """Fraction of sentences carrying no [n] citation marker.

    Deterministic proxy for grounding: every claim sentence should trace
    to at least one cited chunk (AGENTS.md citation rule). Short fragments
    (headings, connectives) are still counted — keep the metric strict.
    """
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(answer) if s.strip()]
    if not sentences:
        return 0.0
    ungrounded = [s for s in sentences if not _CITATION_MARKER.search(s)]
    return len(ungrounded) / len(sentences)


def citation_correctness(
    cited_chunk_ids: Sequence[str],
    retrieved_chunk_ids: Sequence[str],
) -> float:
    """Fraction of cited chunks that were actually retrieved this run.

    Cites pointing outside the retrieved context mean the answer drew on
    chunks the pipeline cannot vouch for — a citation-integrity failure.
    """
    if not cited_chunk_ids:
        return 1.0
    retrieved = set(retrieved_chunk_ids)
    return sum(1 for cid in cited_chunk_ids if cid in retrieved) / len(cited_chunk_ids)
