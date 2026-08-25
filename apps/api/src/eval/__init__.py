"""
src/eval/
--------
Offline evaluation system (maturity plan §8, spec: docs/specs/evaluation.md).

- metrics.py  — pure metric functions (recall, nDCG, MRR, ΔNDCG rerank
                verification, citation checks). No I/O, no model calls.
- harness.py  — loads a golden set (JSONL), runs the retrieval pipeline
                per case via an injectable rank function, aggregates
                metrics, and checks regression thresholds.
"""

from src.eval.harness import GoldenCase, load_golden_set, run_retrieval_eval
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
    "GoldenCase",
    "citation_correctness",
    "citation_coverage",
    "delta_ndcg_at_k",
    "load_golden_set",
    "mrr",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
    "run_retrieval_eval",
    "ungrounded_sentence_ratio",
]
