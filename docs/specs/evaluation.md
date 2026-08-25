# Spec: Offline Evaluation Harness

## Purpose

Measure retrieval quality instead of asserting it. The harness replays a
curated golden set of question → expected-chunks cases through the real
retrieval pipeline, computes ranking metrics (including ΔNDCG rerank
verification), and gates regressions in CI. This is the measurement
foundation every later pipeline change (graph refactor, compression,
parent-child) is validated against.

Dependencies: `src/retrieval/pipeline.py` (`retrieve_with_ablation`),
`src/shared/database.py`, golden-set fixtures (`tests/fixtures/eval/`),
ADR-007 pattern for graceful degradation. No new packages.

## Scope

Covers `src/eval/` (`metrics.py` pure functions, `harness.py` runner),
the CLI (`scripts/eval/run_eval.py`), and the golden-set schema.
Does **not** cover LLM-as-judge answer metrics (faithfulness scoring
needs provider calls; deferred until the golden set carries
`expected_answer` fields) or load testing.

## Metric Contracts (all pure functions)

| Metric | Signature | Definition |
|---|---|---|
| `recall_at_k` | (ranked, relevant, k) | fraction of relevant chunks in top k |
| `precision_at_k` | (ranked, relevant, k) | fraction of top k that are relevant |
| `mrr` | (ranked, relevant) | 1/rank of first relevant hit |
| `ndcg_at_k` | (ranked, relevant, k) | binary-gain DCG / ideal DCG |
| `delta_ndcg_at_k` | (pre, post, relevant, k) | nDCG(post) − nDCG(pre); **rerank effectiveness** — positive means Cohere rerank beat fusion order |
| `citation_coverage` | (answer, n) | fraction of citations referenced as `[n]` |
| `ungrounded_sentence_ratio` | (answer) | sentences without any `[n]` marker |
| `citation_correctness` | (cited, retrieved) | cited chunks present in retrieved set |

## Harness Contract

```python
report = await run_retrieval_eval(cases, rank_fn, k=8, thresholds=None)
```

- `rank_fn(question, workspace_id) -> (fusion_ids, reranked_ids)` —
  injectable for tests; default `pipeline_rank_fn` runs the production
  pipeline headlessly against the DB.
- Report shape: `{k, cases_total, cases_failed, aggregates,
  thresholds, passed, cases[]}` — JSON-ready, written verbatim by the CLI.
- Case errors (provider down, empty workspace) are recorded per-case and
  excluded from aggregates; they do not fail other cases.
- Threshold defaults: recall@8 ≥ 0.5, nDCG@8 ≥ 0.4 — CI gate via script
  exit code.

CLI: `uv run python scripts/eval/run_eval.py --golden-set <path> [--k]
[--min-recall] [--min-ndcg] [--min-delta-ndcg] [--limit] [--report]`.
Writes `eval-reports/<timestamp>.json`; exits 1 below any gate.

## Golden Set Schema

JSONL, one case per line (`//` comments and blanks allowed):

    {"id": "q1", "question": "...", "workspace_id": "<uuid>",
     "expected_chunk_ids": ["<chunk-id>", ...], "notes": "..."}

The checked-in fixture documents the schema with placeholder ids and
backs the unit tests (fake `rank_fn`). Production sets reference seeded
workspaces — curate 50–100 cases before trusting aggregate numbers.

## Success Criteria

- Metrics unit-tested against known rankings (exact values).
- Rerank effectiveness is measurable: ΔNDCG computed between fusion
  order and post-rerank order per case.
- One failing case never corrupts the aggregate report.
- Script exits nonzero when gates fail; zero otherwise.
- No live services needed for the test suite (injectable rank_fn).

## Out of Scope (Deferred)

LLM-as-judge faithfulness/correctness scoring, answer-generation eval,
per-document invalidation granularity for the cache, load testing.
