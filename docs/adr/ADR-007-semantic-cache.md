# ADR-007: Semantic Answer Cache (Redis)

## Status

Accepted. Implemented behind a feature flag (`SEMANTIC_CACHE_ENABLED`,
default `false`). Overrides the `PRD.md` Non-Goal "Semantic Cache (Redis)"
per explicit product decision — `PRD.md` Non-Goals updated to reflect the
override.

## Context

Repeat or near-identical questions against the same workspace pay the full
cost every time: query rewrite → hybrid search → rerank → LLM generation
(typically seconds and real token spend). Badges/usage metrics showed the
pipeline is the dominant cost at MVP scale, and the same document set
produces the same answer for a semantically equivalent question.

`Redis` is already a hard dependency (`arq` job queue, rate limiting), and
Cohere embeddings already exist in the retrieval pipeline (`embed_query`,
`search_query` mode, 1024 dims). A cache can be built with zero new
dependencies and zero new infrastructure.

## Constraints

1. No new packages. The cache must use only `redis.asyncio` (already
   pulled in by `arq`) and the existing Cohere `embed_query`.
2. Workspace-scoped. A question in workspace A must never be answered from
   workspace B's cache (different document sets → different answers).
3. The cache is an optimization, never a dependency. Redis or embedding
   failures must degrade to a normal pipeline run — never an error.
4. Citations must survive the cached path. A cached answer carries its
   original citations (ADR pattern: every claim traces to a chunk).
5. Answers go stale when documents change. MVP has no invalidation hooks —
   TTL expiry bounds the staleness window instead.

## Decision

Add a Redis-backed semantic answer cache that intercepts research requests
**before** the agent runs:

- **Two-tier lookup**:
  1. **Exact hash** — normalized question (strip/lowercase/collapse
     whitespace) → SHA-256 → Redis `GET`. Free hit with no embedding call.
  2. **Semantic scan** — embed the query once, fetch the workspace entry
     index, cosine-compare against all stored embeddings, return the best
     match when similarity ≥ `SEMANTIC_CACHE_THRESHOLD` (0.85). Bounded by
     workspace cache size (≤ a few hundred entries within a 1h TTL), so a
     linear scan beats a vector index.
- **Storage layout** (all keys TTL'd at `SEMANTIC_CACHE_TTL`, default 1h):
  - `scache:eq:{ws}:{query_hash}` → STRING entry_id (exact-match index)
  - `scache:e:{entry_id}` → HASH: q, a, cites (JSON), conf, emb (binary
    float32, latin-1-decoded so it round-trips through string-typed Redis),
    ts, ws
  - `scache:idx:{ws}` → SET of entry_ids (semantic-scan index)
- **Feature flag**: `SEMANTIC_CACHE_ENABLED=false` by default; the lookup
  and store paths no-op when disabled.
- **Graceful degradation**: every Redis/embedding call is wrapped in
  try/except; any failure returns a cache miss and the pipeline runs
  normally (mirrors the rate-limit "Redis down → open" pattern).
- **Consumer wiring**: both research transports (WebSocket `/ws` and
  AG-UI SSE `/chat`) check `lookup()` before `run_agent()` and call
  `store()` after a successful run. Cache hits replay the fixed progress
  stage vocabulary so the UX is indistinguishable from a live run, and
  persist a `ResearchRun` row so run history stays complete.
- Shared Redis client extracted to `src/shared/redis.py` so the cache and
  rate limiting share one connection.

## Consequences

**Positives**

- Repeat-question latency drops from seconds to <100ms with zero token
  spend.
- Feature-flagged rollout; flip on when usage justifies it.
- No new infrastructure, packages, or ORM models (Redis-only, no Alembic
  migration).

**Negatives / accepted ceilings**

- **No document-change invalidation.** Ingestion of new/changed documents
  does not evict cache entries; TTL (1h) is the only freshness bound.
  Add ingestion hooks if stale-answer reports appear.
- **Question-keyed only.** Multi-turn conversation context (`history`) is
  ignored for cache keys — recovered by the high similarity threshold +
  short TTL.
- **Linear cosine scan** over the workspace index. Fine at MVP scale;
  swap to Redis Stack HNSW only if a workspace's cache grows past a few
  hundred entries.
- **Answers return whole**, not streamed. Negligible UX impact at <100ms.