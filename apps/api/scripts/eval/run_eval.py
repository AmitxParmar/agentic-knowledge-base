"""
scripts/eval/run_eval.py
------------------------
Run the offline golden-set evaluation against the real retrieval pipeline.

Measures recall@k / nDCG / MRR / ΔNDCG (rerank effectiveness) per case,
aggregates, writes a JSON report, and exits nonzero when aggregates fall
below regression thresholds — wire this into CI after seeding a real
golden set.

Usage (from apps/api/):
    uv run python scripts/eval/run_eval.py --golden-set tests/fixtures/eval/golden_set.jsonl

Requires DATABASE_URL + COHERE_API_KEY + a model provider key: it runs
the production pipeline headlessly, including HyDE generation.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Allow running as `python scripts/eval/run_eval.py` from apps/api/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.shared.models  # noqa: F401 — register ORM models
from src.eval.harness import load_golden_set, pipeline_rank_fn, run_retrieval_eval


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline retrieval eval")
    parser.add_argument(
        "--golden-set",
        type=Path,
        default=Path("tests/fixtures/eval/golden_set.jsonl"),
        help="JSONL golden set path",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Output JSON report path (default: eval-reports/<timestamp>.json)",
    )
    parser.add_argument("--k", type=int, default=8, help="Ranking cutoff for @k metrics")
    parser.add_argument("--min-recall", type=float, default=0.5, help="CI gate: mean recall@k")
    parser.add_argument("--min-ndcg", type=float, default=0.4, help="CI gate: mean nDCG@k")
    parser.add_argument("--min-delta-ndcg", type=float, default=None, help="Optional rerank gate")
    parser.add_argument("--limit", type=int, default=None, help="Evaluate only the first N cases")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    cases = load_golden_set(args.golden_set)
    if args.limit is not None:
        cases = cases[: args.limit]
    if not cases:
        print(f"No golden cases found in {args.golden_set}")
        return 2

    thresholds = {"recall_at_k": args.min_recall, "ndcg_at_k": args.min_ndcg}
    if args.min_delta_ndcg is not None:
        thresholds["delta_ndcg_at_k"] = args.min_delta_ndcg

    report = await run_retrieval_eval(cases, pipeline_rank_fn, k=args.k, thresholds=thresholds)

    report_path = args.report
    if report_path is None:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        report_path = Path("eval-reports") / f"retrieval-eval-{stamp}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    agg = report["aggregates"]
    print(f"Golden set : {args.golden_set} ({report['cases_total']} cases, "
          f"{report['cases_failed']} errored)")
    print(f"Metrics @k={report['k']}: recall={agg['recall_at_k']} "
          f"ndcg={agg['ndcg_at_k']} mrr={agg['mrr']} "
          f"delta_ndcg={agg['delta_ndcg_at_k']} latency={agg['mean_latency_ms']}ms")
    print(f"Gates      : {report['thresholds']}")
    print(f"Report     : {report_path}")
    print("Result     : " + ("PASS" if report["passed"] else "FAIL"))
    return 0 if report["passed"] else 1


def main() -> None:
    args = _parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
