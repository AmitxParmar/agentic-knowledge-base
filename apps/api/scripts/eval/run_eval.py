"""
scripts/eval/run_eval.py
------------------------
Run the offline golden-set evaluation against the real retrieval pipeline.

Measures recall@k / nDCG / MRR / ΔNDCG (rerank effectiveness) per case,
aggregates, writes a JSON report, and exits nonzero when aggregates fall
below regression thresholds. Wired into CI (.github/workflows/ci.yml,
`eval` job) — currently non-blocking until the golden set is real.

With --answers, additionally scores recorded answers offline (no model
calls) with citation_coverage / ungrounded_sentence_ratio /
citation_correctness gates.

Usage (from apps/api/):
    uv run python scripts/eval/run_eval.py --golden-set tests/fixtures/eval/golden_set.jsonl
    uv run python scripts/eval/run_eval.py --answers eval-answers.jsonl --skip-retrieval

Requires DATABASE_URL + COHERE_API_KEY + a model provider key when the
retrieval leg runs: it uses the production pipeline headlessly, including
HyDE generation. The --answers leg needs no live services.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Allow running as `python scripts/eval/run_eval.py` from apps/api/.
# Step 1: put the api root (parent of `src/` and `app/`) on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import src.shared.models  # noqa: F401 — register ORM models
from src.eval.harness import (
    load_answer_records,
    load_golden_set,
    pipeline_rank_fn,
    run_answer_eval,
    run_retrieval_eval,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline retrieval + answer eval")
    parser.add_argument(
        "--golden-set",
        type=Path,
        default=Path("tests/fixtures/eval/golden_set.jsonl"),
        help="JSONL golden set path",
    )
    parser.add_argument(
        "--answers",
        type=Path,
        default=None,
        help="Recorded-answers JSONL path (scored offline, no live services)",
    )
    parser.add_argument(
        "--skip-retrieval",
        action="store_true",
        help="Skip the retrieval leg (answers-only run)",
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
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.8,
        help="CI gate: mean citation coverage of recorded answers",
    )
    parser.add_argument(
        "--max-ungrounded",
        type=float,
        default=0.5,
        help="CI gate: max mean ungrounded-sentence ratio of recorded answers",
    )
    parser.add_argument(
        "--min-correctness",
        type=float,
        default=1.0,
        help="CI gate: mean citation correctness of recorded answers",
    )
    parser.add_argument("--limit", type=int, default=None, help="Evaluate only the first N cases")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    # Step 1: run the retrieval leg unless explicitly skipped.
    retrieval_report: dict | None = None
    if not args.skip_retrieval:
        cases = load_golden_set(args.golden_set)
        if args.limit is not None:
            cases = cases[: args.limit]
        if not cases and args.answers is None:
            print(f"No golden cases found in {args.golden_set}")
            return 2
        if cases:
            thresholds = {"recall_at_k": args.min_recall, "ndcg_at_k": args.min_ndcg}
            if args.min_delta_ndcg is not None:
                thresholds["delta_ndcg_at_k"] = args.min_delta_ndcg
            retrieval_report = await run_retrieval_eval(
                cases, pipeline_rank_fn, k=args.k, thresholds=thresholds
            )

    # Step 2: run the recorded-answers leg when an answers file is given.
    answer_report: dict | None = None
    if args.answers is not None:
        records = load_answer_records(args.answers)
        if args.limit is not None:
            records = records[: args.limit]
        if not records:
            print(f"No answer records found in {args.answers}")
            return 2
        answer_report = run_answer_eval(
            records,
            thresholds={
                "citation_coverage": args.min_coverage,
                "ungrounded_sentence_ratio": args.max_ungrounded,
                "citation_correctness": args.min_correctness,
            },
        )

    if retrieval_report is None and answer_report is None:
        print("Nothing to evaluate (no cases and no --answers).")
        return 2

    # Step 3: persist the report(s) and print a combined verdict.
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    ok = True
    legs = [
        (retrieval_report, "retrieval-eval"),
        (answer_report, "answer-eval"),
    ]
    both = retrieval_report is not None and answer_report is not None
    for report, prefix in legs:
        if report is None:
            continue
        if args.report is not None and not both:
            path = args.report
        elif args.report is not None:
            path = args.report.with_name(f"{args.report.stem}-{prefix}{args.report.suffix}")
        else:
            path = Path("eval-reports") / f"{prefix}-{stamp}.json"
        _write_report(path, report)
    agg = None
    if retrieval_report is not None:
        agg = retrieval_report["aggregates"]
        print(
            f"Retrieval  : {args.golden_set} ({retrieval_report['cases_total']} cases, "
            f"{retrieval_report['cases_failed']} errored) @k={retrieval_report['k']}: "
            f"recall={agg['recall_at_k']} ndcg={agg['ndcg_at_k']} mrr={agg['mrr']} "
            f"delta_ndcg={agg['delta_ndcg_at_k']} latency={agg['mean_latency_ms']}ms"
        )
        ok = ok and retrieval_report["passed"]
    if answer_report is not None:
        agg = answer_report["aggregates"]
        print(
            f"Answers    : {args.answers} ({answer_report['cases_total']} cases): "
            f"coverage={agg['citation_coverage']} "
            f"ungrounded={agg['ungrounded_sentence_ratio']} "
            f"correctness={agg['citation_correctness']}"
        )
        ok = ok and answer_report["passed"]
    print("Result     : " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def _write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report     : {path}")


def main() -> None:
    args = _parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
