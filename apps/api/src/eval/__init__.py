"""
src/eval/
--------
Offline evaluation system (maturity plan §8, spec: docs/specs/evaluation.md).

- metrics.py  — pure metric functions (recall, nDCG, MRR, ΔNDCG rerank
                verification, citation checks). No I/O, no model calls.
- harness.py  — loads a golden set (JSONL), runs the retrieval pipeline
                per case via an injectable rank function, aggregates
                metrics, and checks regression thresholds. Also scores
                recorded answers (no model calls) via run_answer_eval.
"""

from src.eval.harness import (
    AnswerRecord,
    GoldenCase,
    load_answer_records,
    load_golden_set,
    run_answer_eval,
    run_retrieval_eval,
)
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

__all__ = [
    "AnswerRecord",
    "GoldenCase",
    "citation_correctness",
    "citation_coverage",
    "delta_ndcg_at_k",
    "load_answer_records",
    "load_golden_set",
    "mrr",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
    "run_answer_eval",
    "run_retrieval_eval",
    "ungrounded_sentence_ratio",
]
