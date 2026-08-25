"""
tests/eval/test_harness.py
--------------------------
Harness behavior with an injectable fake rank_fn — no DB, no providers.
Uses the checked-in fixture (tests/fixtures/eval/golden_set.jsonl) as the
golden set so the schema stays exercised end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.eval.harness import GoldenCase, load_golden_set, run_retrieval_eval

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "eval" / "golden_set.jsonl"

# Deterministic fake "corpus": question → (fusion order, reranked order).
# Expected ids from the fixture: q1 {chunk-refund-a, chunk-refund-b},
# q2 {chunk-budget-minutes}, q3 {chunk-retry-design, chunk-retry-config}.
_FAKE_RANKINGS: dict[str, tuple[list[str], list[str]]] = {
    # q1: rerank pulls both relevant chunks into top-2 → recall 1.0, ΔNDCG > 0
    "What refund window does the policy allow?": (
        ["noise-1", "chunk-refund-a", "noise-2", "chunk-refund-b"],
        ["chunk-refund-a", "chunk-refund-b", "noise-1", "noise-2"],
    ),
    # q2: relevant chunk found only after rerank demotes noise
    "Who approved the Q3 budget override?": (
        ["noise-1", "noise-2", "noise-3", "chunk-budget-minutes"],
        ["chunk-budget-minutes", "noise-1", "noise-2", "noise-3"],
    ),
    # q3: one of two relevant chunks missed entirely → recall 0.5
    "How does the retry backoff schedule work?": (
        ["noise-1", "chunk-retry-design"],
        ["noise-1", "chunk-retry-design"],
    ),
}


async def _fake_rank(question: str, workspace_id: str) -> tuple[list[str], list[str]]:
    del workspace_id
    return _FAKE_RANKINGS[question]


def _cases() -> list[GoldenCase]:
    return load_golden_set(FIXTURE)


def test_load_golden_set_parses_fixture() -> None:
    cases = _cases()
    assert [c.id for c in cases] == ["q1", "q2", "q3"]
    assert len(cases[0].expected_chunk_ids) == 2
    assert all(c.workspace_id and c.question for c in cases)


def test_load_golden_set_rejects_bad_line(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"id": "ok", "question": "?", "workspace_id": "w"}\nnot json\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        load_golden_set(bad)


def test_load_golden_set_requires_fields(tmp_path: Path) -> None:
    bad = tmp_path / "missing.jsonl"
    bad.write_text('{"id": "x"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="question"):
        load_golden_set(bad)


async def test_eval_computes_per_case_metrics() -> None:
    report = await run_retrieval_eval(_cases(), _fake_rank, k=4)

    by_id = {c["case_id"]: c for c in report["cases"]}

    # q1: both relevant chunks at ranks 1-2 post-rerank.
    q1 = by_id["q1"]
    assert q1["recall_at_k"] == 1.0
    assert q1["mrr"] == 1.0
    assert q1["delta_ndcg_at_k"] > 0

    # q2: first hit at rank 1 post-rerank vs rank 4 pre-rerank.
    q2 = by_id["q2"]
    assert q2["mrr"] == 1.0
    assert q2["delta_ndcg_at_k"] > 0

    # q3: one of two expected chunks missing → recall 0.5, no rerank change.
    q3 = by_id["q3"]
    assert q3["recall_at_k"] == 0.5
    assert q3["delta_ndcg_at_k"] == 0.0


async def test_eval_aggregates_and_default_gates() -> None:
    report = await run_retrieval_eval(_cases(), _fake_rank, k=4)

    agg = report["aggregates"]
    assert agg["cases_scored"] == 3
    assert report["cases_failed"] == 0
    # Mean recall = (1.0 + 1.0 + 0.5) / 3, rounded to 4 decimals by _aggregate.
    assert agg["recall_at_k"] == 0.8333
    # Default gates: recall ≥ 0.5 ✓, nDCG ≥ 0.4 — computed values are higher.
    assert report["passed"] is True


async def test_eval_threshold_failure_marks_report_failed() -> None:
    report = await run_retrieval_eval(
        _cases(), _fake_rank, k=4, thresholds={"recall_at_k": 0.99}
    )
    assert report["aggregates"]["recall_at_k"] < 0.99
    assert report["passed"] is False


async def test_eval_case_error_is_isolated() -> None:
    async def flaky_rank(question: str, workspace_id: str) -> tuple[list[str], list[str]]:
        if "budget" in question:
            raise RuntimeError("provider down")
        return _FAKE_RANKINGS[question]

    report = await run_retrieval_eval(_cases(), flaky_rank, k=4)

    failed_cases = [c for c in report["cases"] if c["error"]]
    assert len(failed_cases) == 1
    assert "provider down" in failed_cases[0]["error"]

    # The broken case is excluded from aggregates, not zero-folded in.
    assert report["aggregates"]["cases_scored"] == 2
    assert report["cases_failed"] == 1


async def test_eval_empty_corpus_scores_all_zeros_and_fails_gates() -> None:
    async def empty_rank(question: str, workspace_id: str) -> tuple[list[str], list[str]]:
        return [], []

    report = await run_retrieval_eval(_cases(), empty_rank, k=4)
    assert report["aggregates"]["recall_at_k"] == 0.0
    assert report["passed"] is False
