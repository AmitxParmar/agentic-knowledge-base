"""
eval/harness.py
---------------
Offline golden-set evaluation runner.

Loads cases from a JSONL file (one JSON object per line):

    {"id": "q1", "question": "...", "workspace_id": "<uuid>",
     "expected_chunk_ids": ["<chunk-uuid>", ...], "notes": "optional"}

For each case the harness calls an injectable ``rank_fn(question,
workspace_id) -> (fusion_ids, reranked_ids)`` and scores both orderings
against ``expected_chunk_ids``. The default adapter runs the real
retrieval pipeline (``retrieve_with_ablation``) against the configured
database — so eval measures production behavior, not a mock.

The result is a JSON-ready report: per-case metrics, corpus aggregates,
and a threshold pass/fail flag for CI regression gating. Golden sets
referencing real workspaces are seeded separately (scripts/seed_*.py);
the checked-in fixture documents the schema.
"""

from __future__ import annotations

import json
import time
import uuid as _uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.eval.metrics import (
    delta_ndcg_at_k,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

# rank_fn(question, workspace_id) -> (fusion_order_ids, reranked_order_ids)
RankFn = Callable[[str, str], Awaitable[tuple[list[str], list[str]]]]

# CI gate defaults — tighten as the corpus and golden set mature.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "recall_at_k": 0.5,
    "ndcg_at_k": 0.4,
}


@dataclass(frozen=True)
class GoldenCase:
    """One evaluation question with its ground-truth chunk ids."""

    id: str
    question: str
    workspace_id: str
    expected_chunk_ids: list[str]
    notes: str = ""


def load_golden_set(path: str | Path) -> list[GoldenCase]:
    """Parse a JSONL golden set. Blank lines and ``//`` comments allowed."""
    cases: list[GoldenCase] = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"golden set line {line_no}: invalid JSON ({exc})") from exc
            try:
                cases.append(
                    GoldenCase(
                        id=str(raw["id"]),
                        question=str(raw["question"]),
                        workspace_id=str(raw["workspace_id"]),
                        expected_chunk_ids=[str(c) for c in raw.get("expected_chunk_ids", [])],
                        notes=str(raw.get("notes", "")),
                    )
                )
            except KeyError as exc:
                raise ValueError(
                    f"golden set line {line_no}: missing required field {exc}"
                ) from exc
    return cases


async def run_retrieval_eval(
    cases: list[GoldenCase],
    rank_fn: RankFn,
    *,
    k: int = 8,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Evaluate every case and aggregate. Returns a JSON-ready report.

    A case whose rank_fn raises is recorded with an ``error`` and excluded
    from aggregates — one broken case must not poison the whole report.
    """
    results: list[dict[str, Any]] = []
    for case in cases:
        results.append(await _eval_case(case, rank_fn, k))

    ok = [r for r in results if r["error"] is None]
    failed = len(results) - len(ok)
    aggregates = _aggregate(ok, k)

    gates = thresholds if thresholds is not None else dict(DEFAULT_THRESHOLDS)
    passed = all(aggregates.get(metric, 0.0) >= target for metric, target in gates.items())

    return {
        "k": k,
        "cases_total": len(results),
        "cases_failed": failed,
        "aggregates": aggregates,
        "thresholds": gates,
        "passed": passed,
        "cases": results,
    }


async def _eval_case(case: GoldenCase, rank_fn: RankFn, k: int) -> dict[str, Any]:
    relevant = set(case.expected_chunk_ids)
    base: dict[str, Any] = {"case_id": case.id, "question": case.question, "k": k}
    try:
        started = time.perf_counter()
        fusion_ids, reranked_ids = await rank_fn(case.question, case.workspace_id)
        latency_ms = int((time.perf_counter() - started) * 1000)
    except Exception as exc:
        base.update(error=f"{type(exc).__name__}: {exc}")
        return base

    base.update(
        error=None,
        latency_ms=latency_ms,
        retrieved=len(reranked_ids),
        expected=len(relevant),
        recall_at_k=recall_at_k(reranked_ids, relevant, k),
        precision_at_k=precision_at_k(reranked_ids, relevant, k),
        mrr=mrr(reranked_ids, relevant),
        ndcg_at_k=ndcg_at_k(reranked_ids, relevant, k),
        # Rerank effectiveness: post-rerank nDCG minus pre-rerank (fusion) nDCG.
        delta_ndcg_at_k=delta_ndcg_at_k(fusion_ids, reranked_ids, relevant, k),
    )
    return base


def _aggregate(results: list[dict[str, Any]], k: int) -> dict[str, float | int]:
    if not results:
        return {
            "recall_at_k": 0.0,
            "precision_at_k": 0.0,
            "mrr": 0.0,
            "ndcg_at_k": 0.0,
            "delta_ndcg_at_k": 0.0,
            "mean_latency_ms": 0,
            "cases_scored": 0,
        }
    count = len(results)

    def mean(field: str) -> float:
        return sum(float(r[field]) for r in results) / count

    return {
        "recall_at_k": round(mean("recall_at_k"), 4),
        "precision_at_k": round(mean("precision_at_k"), 4),
        "mrr": round(mean("mrr"), 4),
        "ndcg_at_k": round(mean("ndcg_at_k"), 4),
        "delta_ndcg_at_k": round(mean("delta_ndcg_at_k"), 4),
        "mean_latency_ms": round(mean("latency_ms")),
        "cases_scored": count,
    }


async def pipeline_rank_fn(question: str, workspace_id: str) -> tuple[list[str], list[str]]:
    """Default RankFn adapter: the real retrieval pipeline against the DB."""
    from src.retrieval.pipeline import retrieve_with_ablation
    from src.shared.database import SessionLocal

    async with SessionLocal() as session:
        candidates, final = await retrieve_with_ablation(
            question, _uuid.UUID(workspace_id), session
        )
    return [c.chunk_id for c in candidates], [c.chunk_id for c in final]
