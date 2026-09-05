# Enterprise Agentic Knowledgebase — Impact Highlights

> Monorepo: FastAPI + LangGraph + pgvector (Neon) + Cohere + LiteLLM + Next.js 16 (AG-UI SSE) + Redis/Arq + Backblaze B2
> Use these bullets verbatim on a resume. Grouped by outcome.

## 1. Cost Optimization
- Implemented 3-layer caching with zero new infrastructure: **Semantic Answer Cache** (Redis, 2-tier exact-hash + cosine ≥0.85 semantic scan, 1h TTL), **Retrieval Result Cache** (workspace+query, 600s, corpus-change eviction), and **in-process Embedding LRU** (1K entries) — bypasses full HyDE + hybrid + rerank + LLM pipeline on repeat questions.
- Enforced hard cost guardrails: `AGENT_TOKEN_BUDGET=60k` + `MAX_ITERATIONS=5` + `AGENT_RUN_TIMEOUT=60s` / `AGENT_ITERATION_TIMEOUT=30s` routing to synthesis — prevents runaway token spend on long-tail queries.
- Built unified **Model Gateway** via LiteLLM (`complete` / `complete_with_tools`) with Groq `llama-3.3-70b` → OpenRouter fallback; provider/model swap via env only, retries + fallbacks handled by LiteLLM, no agent code change.

## 2. Performance & Retrieval Quality
- Built production hybrid retrieval: **HyDE expansion** → parallel **dense pgvector** (`vector(1024)`) + **Postgres FTS** (`tsvector` + GIN, `ts_rank_cd`) → **RRF (k=60)** → **Cohere rerank-v3** (cross-encoder) → dedup + per-document cap (3) + parent-context expansion (adjacent sibling merge).
- Migrated vector store from in-process Turbovec to **pgvector column** `chunks.embedding` on Neon (migration `9f2a1c3b4e5d`) — eliminated 10–30s cold-start rebuild + re-embedding, single source of truth, workspace-scoped filtering in SQL.
- Isolated latency: `RETRIEVAL_VECTOR_SEARCH_TIMEOUT=5s` wrapped in `asyncio.wait_for` → `RetrievalError` (not 500); embedding batching (`EMBED_BATCH_SIZE=64`, Cohere limit 96) with concurrency semaphore.

## 3. Reliability / Hardening
- Hardened 6-stage ingestion pipeline (extract → chunk → embed → persist) via **arq**: PDF magic-byte/page-count (100)/encryption validation, 100 MB limit, exponential backoff retries (3× + jitter, 0.5s–4s), typed `EmbeddingError` fails loud when `ALLOW_EMBEDDING_FALLBACK=false`.
- Implemented **corpus-aware invalidation**: document ingest/delete evicts both semantic and retrieval caches for that workspace — stale answers impossible; TTL is only the backstop.
- Added **rate limiting** (Redis fixed-window, 5 uploads/min + 20 chats/min per IP) and split health probes: `/healthz` (liveness) + `/readyz` (DB + Redis + cached Cohere probe).

## 4. Agentic Architecture
- Composed **LangGraph** pipeline: **planner node** (cheap model, 1–3 aspects, JSON parse-tolerant, never fails run) → **ReAct researcher** (`retrieve_evidence` tool, citation-at-retrieval) → **synthesize node**; graph checkpointed via Postgres (recoverable runs).
- Designed for V1 scale without rewrite (ADR-001): single-node graph today is structurally identical to three-node Planner → Researcher → Critic tomorrow; deferred features (Critic, plan cache, MCP) gated by spec + measurement per `AGENTS.md`.
- End-to-end **citation integrity**: every retrieved chunk carries `chunk_id`/`document_id`/`source_ref`/`relevance_score`; persisted as `citations` rows, verified by `test_citation_survival` integration test (never reconstructed from final answer text).

## 5. Observability & Evaluation
- Wired **Logfire + Langfuse** tracing for every agent run, retrieval step, and gateway call (input/output/usage/citations/tokens) — single `configure()` call in app lifespan.
- Shipped **offline eval harness** (`src/eval` + `scripts/eval/run_eval.py`) on JSONL golden set: `recall@k`, `precision@k`, `MRR`, `nDCG@k`, `ΔnDCG` (rerank effectiveness), `citation_coverage` — JSON report + CI gate thresholds; provider-down cases isolated per-case.

## 6. Security & Scale
- Added **JWT auth** (ADR-008: HS256 via PyJWT, `AUTH_MODE=stub|jwt`, 12h TTL, `scripts/mint_token.py`); workspace isolation enforced at dependency layer, zero migration for local dev; generic 401 never leaks expired vs malformed.
- Infra: **Neon Postgres + pgvector + Upstash Redis + Backblaze B2 (S3-compatible) + single Render service** (`max_jobs=4` arq workers); Turborepo + pnpm monorepo with shared `packages/ui` and strict `conventions.md` (feature-first, no utils dump).

---
*Source of truth: `apps/api/src/retrieval/pipeline.py`, `apps/api/src/research/agent.py`, `apps/api/src/shared/semantic_cache.py`, `apps/api/src/shared/model_gateway.py`, `docs/specs/*`, `docs/adr/ADR-002` & `ADR-003` updates, `docs/conventions.md`.*
