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

This spec covers the cache module and its wiring into the research
transports (`/ws` WebSocket and `/chat` AG-UI SSE). It does **not** cover
document-change invalidation, vector-index scaling, or cache analytics —
deferred per ADR-007.

## Feature Flag

All behavior is gated by `SEMANTIC_CACHE_ENABLED` (default `false`).
When disabled, `lookup()` returns `None` and `store()` no-ops — the
research pipeline is untouched.

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
embedding), and the workspace index set — all TTL'd at
`SEMANTIC_CACHE_TTL` (default 3600s). `store()` embeds the question with
the same `embed_query` call the lookup path uses, keeping stored and
lookup vectors in one space.

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

## Out of Scope (Deferred)

Document-change invalidation, Redis Stack/HNSW vector index, cache
hit-rate analytics, streaming cached answers token-by-token. See ADR-007
Consequences for rationale.