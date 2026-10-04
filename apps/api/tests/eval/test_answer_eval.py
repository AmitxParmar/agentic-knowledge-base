"""
tests/eval/test_answer_eval.py
------------------------------
Answer-level eval over recorded answers — deterministic, no model calls.
Covers load_answer_records, run_answer_eval scoring, and gate directions
(coverage/correctness are minimums, ungrounded ratio is a maximum).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.eval.harness import (
    AnswerRecord,
    load_answer_records,
    run_answer_eval,
)


def _record(**overrides) -> AnswerRecord:
    base = {
        "case_id": "q1",
        "answer": "Refunds take 30 days [1].",
        "cited_chunk_ids": ["c1"],
        "retrieved_chunk_ids": ["c1", "c2"],
    }
    base.update(overrides)
    return AnswerRecord(**base)


def test_load_answer_records_parses_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "answers.jsonl"
    path.write_text(
        "// recorded answers for eval\n"
        + json.dumps(
            {
                "case_id": "q1",
                "answer": "Refunds take 30 days [1].",
                "cited_chunk_ids": ["c1"],
                "retrieved_chunk_ids": ["c1", "c2"],
            }
        )
        + "\n\n",
        encoding="utf-8",
    )
    records = load_answer_records(path)
    assert len(records) == 1
    assert records[0].case_id == "q1"


def test_load_answer_records_rejects_missing_field(tmp_path: Path) -> None:
    path = tmp_path / "answers.jsonl"
    path.write_text(json.dumps({"case_id": "q1"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required field"):
        load_answer_records(path)


def test_answer_eval_scores_grounded_answer() -> None:
    report = run_answer_eval([_record()])
    case = report["cases"][0]
    assert case["citation_coverage"] == 1.0
    assert case["citation_correctness"] == 1.0
    assert case["ungrounded_sentence_ratio"] == 0.0
    assert report["passed"] is True


def test_answer_eval_catches_hallucinated_citation() -> None:
    record = _record(cited_chunk_ids=["c1", "c-ghost"])
    report = run_answer_eval([record])
    assert report["cases"][0]["citation_correctness"] == 0.5
    assert report["passed"] is False  # correctness gate is 1.0


def test_answer_eval_catches_low_coverage() -> None:
    # Two chunks cited but only [1] marked in the answer → coverage 0.5.
    record = _record(
        answer="Refunds take 30 days [1].",
        cited_chunk_ids=["c1", "c2"],
        retrieved_chunk_ids=["c1", "c2"],
    )
    report = run_answer_eval([record], thresholds={"citation_coverage": 0.8})
    assert report["cases"][0]["citation_coverage"] == 0.5
    assert report["passed"] is False


def test_ungrounded_gate_is_a_maximum() -> None:
    # A 0.5 ratio must FAIL a 0.4 maximum but PASS a 0.5 maximum.
    record = _record(
        answer="Refunds take 30 days [1]. Shipping is free.",
        cited_chunk_ids=["c1"],
    )
    assert (
        run_answer_eval([record], thresholds={"ungrounded_sentence_ratio": 0.4})["passed"] is False
    )
    assert (
        run_answer_eval([record], thresholds={"ungrounded_sentence_ratio": 0.5})["passed"] is True
    )


def test_answer_eval_empty_input_fails() -> None:
    report = run_answer_eval([])
    assert report["aggregates"]["cases_scored"] == 0
    assert report["passed"] is False
