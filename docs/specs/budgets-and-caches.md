# Spec: Run Budgets + Retrieval & Embedding Caches

## Purpose

Bound per-run cost and eliminate redundant work:

1. **Token budget** - a research run that burns more than
   `AGENT_TOKEN_BUDGET` cumulative LLM tokens is routed to final
   synthesis instead of looping again. Hard cost cap; tokens are the
   cost proxy (pricing tables are out of scope).
2. **Query-embedding LRU** - `embed_query` results are cached in-process
   (`EMBED_QUERY_CACHE_SIZE` entries). Same text recurs across agent
   iterations, near-duplicate questions, semantic-cache lookups.
3. **Retrieval cache** - final selected chunks cached in Redis per
   (workspace, exact question) at `RETRIEVAL_CACHE_TTL` (default 600s),
   short-circuiting HyDE + hybrid search + rerank on repeats.

Dependencies: existing Redis client (`src/shared/redis.py`), settings,
ADR-007 degradation pattern. No new packages.

## Contracts

### Token budget (research-pipeline routing)
- `_route_after_research` routes to `synthesize` when
  `tokens_used >= AGENT_TOKEN_BUDGET`, logging
  `research.token_budget_exceeded`.
- Time budgets are unchanged (`AGENT_RUN_TIMEOUT`,
  `AGENT_ITERATION_TIMEOUT`). Together: iteration / time / token caps.

### Embedding LRU (embedder)
- Keyed on exact query string; LRU eviction at
  `EMBED_QUERY_CACHE_SIZE`; per-worker process lifetime (no TTL -
  embedding of a fixed string is deterministic within a model version).
- Only `embed_query` is cached; batch ingestion (`embed_texts`) is not.

### Retrieval cache (`src/shared/retrieval_cache.py`)
- Keys: `rcache:{ws}:{query_hash}` -> JSON chunk list;
  `rcache:idx:{ws}` -> SET of hashes. TTL'd at `RETRIEVAL_CACHE_TTL`.
- Gated by `RETRIEVAL_CACHE_ENABLED` (default true); every operation is
  best-effort - Redis failures degrade to misses, never errors.
- **Invalidation:** `invalidate_retrieval_cache(ws)` evicts all entries
  for a workspace; called wherever the corpus changes (ingestion done +
  document delete), alongside `SemanticCache.invalidate_workspace`.
  An answer is only valid for the corpus that produced it.
- On a hit, both ranking stages returned by `retrieve_with_ablation`
  are the cached selection (fusion order unknown) - DeltaNDCG reads 0
  for cached cases, neutral for rerank verification.

## Success Criteria

- Routing trips to synthesis exactly at the budget boundary (tested).
- Second identical `embed_query` makes no second provider call (tested).
- Retrieval cache round-trips, isolates workspaces, invalidates cleanly,
  and no-ops when disabled or Redis is down (tested).
- Citations survive a cache hit byte-for-byte (chunks serialized whole).

## Out of Scope (Deferred)

Dollar-cost metering with pricing tables, cross-process embedding
caches, Redis Stack semantic similarity for retrieval-cache keys
(exact-hash only today).
