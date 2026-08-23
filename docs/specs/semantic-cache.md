# Spec: Semantic Answer Cache

## Purpose

Short-circuit research runs for questions that have already been answered
well in the same workspace. A semantically similar cached question
(cosine ≥ 0.85) returns the stored answer with its original citations —
skipping the full retrieval + LLM pipeline (ADR-007).

## Dependencies

`src/shared/redis.py` (shared Redis client), `src/shared/semantic_cache.py`
(core module), Cohere `embed_query` (`docs/specs/retrieval.md` — same
`search_query` embedding space the retrieval pipeline uses), ADR-007.

## Scope

This spec covers the cache module, its wiring into the research
transports (`/ws` WebSocket and `/chat` AG-UI SSE), document-change
invalidation, and hit-rate metrics. Vector-index scaling (Redis Stack
HNSW) remains out of scope per ADR-007.

## Feature Flag

All lookup/store behavior is gated by `SEMANTIC_CACHE_ENABLED`
(default `false`). When disabled, `lookup()` returns `None` and
`store()` no-ops — the research pipeline is untouched.
**Exception:** `invalidate_workspace()` runs regardless of the flag so
entries written before a flag flip can never outlive their corpus.

## Lookup Contract

| Input | Description |
|---|---|
| `workspace_id` | Scopes the cache — answers never cross workspaces |
| `question` | The user's natural-language question |

| Output | Description |
|---|---|
| `CacheHit` or `None` | `CacheHit`: `answer`, `citations` (original chunk refs), `confidence`, `similarity`, `entry_id` |

**Two-tier lookup:**

1. **Exact hash** — normalize question (strip / lowercase / collapse
   whitespace) → SHA-256 → `GET scache:eq:{ws}:{hash}`. Hit → return entry
   with `similarity=1.0`, no embedding call.
2. **Semantic scan** — `embed_query(question)`, fetch workspace index
   (`SMEMBERS scache:idx:{ws}`), pipeline-`HGETALL` entries, cosine-compare,
   return the best match if `similarity ≥ SEMANTIC_CACHE_THRESHOLD` (0.85).

## Store Contract

Called after a successful `run_agent()` invocation:

```python
await cache.store(workspace_id, question, answer, citations, confidence)
```

Writes the exact-hash pointer, the entry hash (with binary float32
embedding and the `qh` query-hash field), and the workspace index set —
all TTL'd at `SEMANTIC_CACHE_TTL` (default 3600s). `store()` embeds the
question with the same `embed_query` call the lookup path uses, keeping
stored and lookup vectors in one space.

## Invalidation Contract

An answer is only valid for the corpus that produced it, so any corpus
change evicts the whole workspace cache:

```python
removed = await cache.invalidate_workspace(workspace_id)  # → int
```

- Called by `_run_pipeline()` when a document finishes indexing
  (`src/ingestion/pipeline.py`) and by
  `DELETE /api/ingestion/documents/{id}` (`src/ingestion/router.py`).
- Evicts every entry hash, its derived exact-match key (via each entry's
  stored `qh` field — no keyspace scan), and the workspace index set.
- Best-effort: Redis failures never raise; returns the eviction count.
- Workspace-granular by design (ADR-007): one changed document evicts all
  cached answers in that workspace.

## Metrics Contract

Per-workspace counters in a Redis hash (`scache:m:{ws}`, TTL ≥ 24h):

| Field | Bumped when |
|---|---|
| `hits_exact` | Tier-1 exact-hash hit |
| `hits_semantic` | Tier-2 semantic hit |
| `misses` | Lookup resolves below threshold or empty index |
| `stores` | Answer persisted |
| `invalidations` | Workspace cache evicted |

Read via `stats(workspace_id)` (adds a computed `lookups` total) and
exposed at `GET /api/research/cache/stats`, scoped by workspace.
Hit rate = (`hits_exact` + `hits_semantic`) / `lookups`.

## Behavior — Consumer Wiring

Both research transports (research router, WS and SSE paths):

1. `hit = await cache.lookup(workspace_id, question)` **before**
   `run_agent()`.
2. **On hit**: create a `ResearchRun` marked complete with the cached
   answer, commit, replay the fixed progress stages (`docs/ui/ux.md`
   vocabulary — `SEARCHING → REVIEWING → GENERATING → FINALIZING`), send
   the answer + citations in the same wire format as a live run
   (`chunk_id`, `source_ref`, `relevance_score`), emit done, close.
3. **On miss**: run the pipeline as today. After a successful run, call
   `cache.store()` — best-effort, never blocks or raises.

## Success Criteria

- Repeat question (same wording) → exact-hash hit, no embedding call.
- Paraphrase (cosine ≥ 0.85) → semantic hit, cached answer returned.
- Unrelated question → miss, full pipeline runs, answer stored.
- Workspace A's cache never answers workspace B's questions.
- Redis down / embed failure / feature disabled → lookup returns `None`,
  pipeline runs normally.
- Cached responses carry their original citations end-to-end.
- Document indexed or deleted → workspace cache empty; next lookup misses.
- Invalidation in workspace A leaves workspace B's entries intact.

## Out of Scope (Deferred)

Redis Stack/HNSW vector index, streaming cached answers token-by-token,
per-document invalidation granularity. See ADR-007 Consequences for
rationale.