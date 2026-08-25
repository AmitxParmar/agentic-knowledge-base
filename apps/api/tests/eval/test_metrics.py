"""
tests/eval/test_metrics.py
--------------------------
Exact-value unit tests for the pure metric functions. No I/O, no mocks.
"""

from __future__ import annotations

import math

from src.eval.metrics import (
    citation_correctness,
    citation_coverage,
    delta_ndcg_at_k,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    ungrounded_sentence_ratio,
)

RANKED = ["a", "b", "c", "d", "e"]
RELEVANT = {"b", "d"}


# ── recall / precision / MRR ──────────────────────────────────────────────────


def test_recall_counts_relevant_in_top_k() -> None:
    assert recall_at_k(RANKED, RELEVANT, 1) == 0.0
    assert recall_at_k(RANKED, RELEVANT, 2) == 0.5
    assert recall_at_k(RANKED, RELEVANT, 5) == 1.0
    assert recall_at_k(RANKED, RELEVANT, 100) == 1.0


def test_recall_empty_relevant_is_zero() -> None:
    assert recall_at_k(RANKED, set(), 5) == 0.0


def test_precision_fraction_of_top_k() -> None:
    assert precision_at_k(RANKED, RELEVANT, 2) == 0.5
    assert precision_at_k(RANKED, RELEVANT, 4) == 0.5
    assert precision_at_k([], RELEVANT, 3) == 0.0
    assert precision_at_k(RANKED, RELEVANT, 0) == 0.0


def test_mrr_first_hit_wins() -> None:
    assert mrr(["x", "b", "y"], RELEVANT) == 0.5
    assert mrr(["d", "x", "b"], RELEVANT) == 1.0
    assert mrr(["x", "y", "z"], RELEVANT) == 0.0


# ── nDCG ──────────────────────────────────────────────────────────────────────


def test_ndcg_perfect_ranking_is_one() -> None:
    # Both relevant chunks at ranks 1-2 → ideal ordering.
    assert ndcg_at_k(["b", "d", "a", "c"], RELEVANT, 4) == 1.0


def test_ndcg_discounts_late_hits() -> None:
    score = ndcg_at_k(["a", "c", "e", "b", "d"], RELEVANT, 5)
    expected = (1 / math.log2(5) + 1 / math.log2(6)) / (1 / math.log2(2) + 1 / math.log2(3))
    assert math.isclose(score, expected)


def test_ndcg_zero_on_miss() -> None:
    assert ndcg_at_k(["x", "y"], RELEVANT, 2) == 0.0
    assert ndcg_at_k(RANKED, set(), 5) == 0.0


def test_delta_ndcg_positive_when_post_beats_pre() -> None:
    relevant = {"good"}
    pre = ["meh1", "meh2", "good"]
    post = ["good", "meh1", "meh2"]
    assert delta_ndcg_at_k(pre, post, relevant, 3) > 0


def test_delta_ndcg_negative_when_rerank_hurts() -> None:
    relevant = {"good"}
    pre = ["good", "meh1", "meh2"]
    post = ["meh1", "meh2", "good"]
    assert delta_ndcg_at_k(pre, post, relevant, 3) < 0


def test_delta_ndcg_symmetric_orders_cancel() -> None:
    assert delta_ndcg_at_k(RANKED, list(RANKED), RELEVANT, 5) == 0.0


# ── citation metrics ──────────────────────────────────────────────────────────


def test_citation_coverage_counts_referenced_markers() -> None:
    answer = "The policy allows 30 days [1], except in the EU [2]."
    assert citation_coverage(answer, 2) == 1.0
    assert citation_coverage(answer, 3) == 2 / 3


def test_citation_coverage_no_markers_is_zero() -> None:
    assert citation_coverage("Nothing cited here.", 2) == 0.0


def test_citation_coverage_no_citations_is_perfect() -> None:
    assert citation_coverage("Anything.", 0) == 1.0


def test_ungrounded_sentence_ratio_mixed_answer() -> None:
    grounded = "Refunds take 30 days [1]."
    ungrounded = "Trust me on this."
    ratio = ungrounded_sentence_ratio(f"{grounded} {ungrounded}")
    assert ratio == 0.5


def test_ungrounded_sentence_ratio_all_grounded() -> None:
    assert ungrounded_sentence_ratio("A [1]. B [2]! C [3]?") == 0.0


def test_ungrounded_sentence_ratio_empty_answer() -> None:
    assert ungrounded_sentence_ratio("") == 0.0


def test_citation_correctness_cites_within_retrieved() -> None:
    cited = ["c1", "c2"]
    retrieved = ["c1", "c3", "c4"]
    assert citation_correctness(cited, retrieved) == 0.5


def test_citation_correctness_no_citations_is_perfect() -> None:
    assert citation_correctness([], ["c1"]) == 1.0
