# Impactful Engineering Improvements

> Prioritized engineering opportunities for the Agentic Research Workspace.
> Derived from current code (`apps/api`, `apps/web`), `docs/PRD.md`,
> `docs/REMAINING.md`, ADRs, and specs — not generic RAG advice.
>
> **How to use this doc**
> - Prefer high-impact, high-confidence items first.
> - Do **not** build Phase 2 agents (Planner/Critic/cache/RBAC) until the
>   core loop is real and measured — see `AGENTS.md` and PRD Non-Goals.
> - Each item lists *why it matters*, *current gap*, and *concrete fix*.
>
> Last updated: 2026-10-16

---

## Executive summary

Scaffolding for the MVP vertical slice is largely present:

**upload → arq ingest → hybrid retrieve → LangGraph researcher → cited answer**

The highest-leverage work is **not** new architecture. It is making the
existing path **honest, durable, and measurable**:

1. Stop silent quality degradation (hash embeddings, uniform rerank, numpy ANN).
2. Fix multi-process vector-index correctness (API vs worker do not share memory).
3. Persist retrieval infrastructure (tsvector + GIN, optional embedding storage).
4. Prove the loop with real E2E tests and CI.
5. Harden ops (health, retries, limits, deploy) before multi-agent features.

If you only do five things, do **P0**.

---

## Priority legend

| Priority | Meaning |
|---|---|
| **P0** | Blocks real product quality or correctness today |
| **P1** | Strong reliability / DX / ops multiplier before users |
| **P2** | Architecture leverage once the core loop works |
| **P3** | Nice-to-have or wait for usage signal |

| Effort | Rough size |
|---|---|
| **S** | Hours |
| **M** | 1–3 days |
| **L** | Multi-day / multi-PR |

---

## P0 — Make the core loop real

### 1. Kill silent quality fallbacks

**Why it matters:** The system can “succeed” while returning garbage. Hash
embeddings and uniform rerank scores look like a working pipeline in logs and
tests but produce near-random ranking.

**Current gap**

| Path | Fallback when real backend is down |
|---|---|
| `src/retrieval/embedder.py` | SHA-256 hash vectors (not semantic) |
| `src/retrieval/embedder.py` rerank | All scores `1.0` |
| `src/retrieval/vector_index.py` | In-process numpy cosine store |

```text
# embedder.py today
except Exception:
    return _local_embed(texts)   # silent success with fake vectors
```

**Impactful fix**

- Introduce an explicit `EMBEDDING_MODE=real|strict|dev_hash`.
- Default **strict** in non-dev: fail the request/job if embed/rerank is unreachable.
- Emit a hard metric/log flag `retrieval.degraded=true` whenever fallback is used.
- Never let research runs complete with degraded retrieval without surfacing it
  to the client (`type: error` or a visible “search quality degraded” stage).

**Effort:** S–M · **Unblocks:** meaningful search, honest demos

---

### 2. Fix multi-process vector index (API vs worker)

**Why it matters:** This is a latent **correctness bug**, not a polish item.

- Ingestion worker upserts vectors into **its** process-local `VectorIndex`.
- Research API searches **its** process-local `VectorIndex`.
- They do not share memory. Rebuild-on-API-startup re-embeds from Postgres,
  but worker upserts after startup are invisible to the API until rebuild.

**Current gap**

- `get_vector_index()` is a module singleton per process.
- Worker never notifies API to rebuild.
- No durable vector store shared across processes (in-process ANN; the
  numpy fallback is a dict).

**Impactful fix (pick one, ADR if new dep)**

| Option | Pros | Cons |
|---|---|---|
| **A. Persist embeddings in Postgres** + rebuild/load on API boot + pub/sub rebuild on ingest done | Fits ADR-002 (“Postgres authoritative”) | Schema migration; larger rows |
| **B. Shared ANN service** (dedicated ANN / pgvector) | True multi-process | New operational surface |
| **C. Always re-query from PG + embed-on-read for dense** (temporary) | Correct, simple | Slow; not production long-term |

Recommended near-term: **A** — store `chunks.embedding vector` (or `float[]` /
bytea) at ingest time; API loads into pgvector (or numpy fallback) at startup
and on `ingestion.done` events (Redis pub/sub or arq completion hook).

**Effort:** M · **Unblocks:** multi-worker deploy, consistent retrieval

---

### 3. Add real full-text search infrastructure

**Why it matters:** Hybrid PostgreSQL FTS is half of retrieval quality. Today
`ts_rank_cd` runs over the persisted `chunks.tsv` generated column with a GIN
index — no per-query `to_tsvector()` recomputation.

**Current gap**

- Migration creates tables but **no** `chunks.tsv` / GIN / trigger
  (called out in `ROADMAP.md` Step 4 and `REMAINING.md`).
- Model comment mentions tsvector; column is not actually managed.

**Impactful fix**

```sql
ALTER TABLE chunks ADD COLUMN tsv tsvector;
CREATE INDEX chunks_tsv_idx ON chunks USING GIN (tsv);
-- trigger: NEW.tsv := to_tsvector('english', NEW.text)
```

- Switch `_fts_search` to rank on `Chunk.tsv` (or raw SQL) instead of
  `to_tsvector` on every row.
- Backfill existing chunks in the migration.

**Effort:** S · **Unblocks:** keyword recall, hybrid fusion value

---

### 4. Run real embedding + rerank services

**Why it matters:** Embedding quality drives hybrid search quality. Production
uses Cohere embed-v3 + rerank-v3 via the embedder; reranking is a true
cross-encoder, not cosine-of-embeddings.

**Current gap**

- Rerank fallbacks (e.g. LM Studio, local TEI endpoints) are optional paths;
  the primary path is Cohere embed-v3 / rerank-v3.
- Rerank quality depends on the configured rerank model.

**Impactful fix**

- Wire embedder to Cohere (`COHERE_EMBED_MODEL`, `COHERE_RERANK_MODEL`) with
  local TEI / LM Studio as optional alt.
- Prefer true cross-encoder scores for final top-k.
- Health-check both endpoints at API/worker startup; refuse to start in
  production if missing (see also #1).

**Effort:** M · **Unlocks:** PRD F4 hybrid search quality

---

### 5. Prove the MVP path end-to-end (definition of done)

**Why it matters:** Code exists; confidence does not. Feature test packages
(`tests/ingestion`, `tests/research`, `tests/retrieval`) are empty stubs.
Integration tests mock the DB/session heavily.

**Current gap**

- ~~No CI workflow in the repo.~~ CI runs ruff + basedpyright + pytest + TS
  lint/typecheck on push/PR (`.github/workflows/ci.yml`, 2026-09-28); the
  golden-set eval job is non-blocking until the golden set is real.
- No automated “PDF upload → job done → question → ≥1 citation” against a
  real (or testcontainers) Postgres + Redis.
- `scratch_test.py` is a manual hub, not a regression suite.

**Impactful fix**

| Layer | What to add |
|---|---|
| Unit | RRF, source_ref builder, stage enum contracts, gateway parse |
| Integration | arq job stages with fake extract/embed |
| Contract | WebSocket message schema vs `docs/ux.md` |
| E2E (optional nightly) | Real PDF + real/mock LLM with recorded fixtures |

Minimum green bar for “MVP works”:

- [ ] PDF upload → `done` without manual steps
- [ ] Question → cited answer over WebSocket
- [ ] ≥1 citation with usable `source_ref`
- [ ] Progress events use only `ux.md` strings
- [x] ruff + basedpyright + pytest green in CI

**Effort:** M · **Unblocks:** safe iteration on everything else

---

## P1 — Backend reliability and production readiness

### 6. Dependency-aware health checks

**Current:** `GET /health` returns `{"status":"ok"}` always.

**Fix:** Expand to check:

- Postgres (`SELECT 1`)
- Redis (PING)
- Embedder / reranker reachability
- Optional: vector index size / last rebuild time

Return **503** when critical deps are down. Orchestrators (Render, k8s)
need this; demos need it too.

**Effort:** S

---

### 7. Ingestion hardening

| Gap | Fix |
|---|---|
| No file size limit | Reject > N MB at upload (e.g. 50MB) |
| No MIME/extension validation | Allowlist by `source_type` |
| No arq retries | `max_tries=3` with backoff on transient errors |
| No dead-letter surface | `GET /jobs/failed` + `POST /jobs/{id}/retry` with row reset (2026-09-28) |
| Retries duplicate chunks | delete-before-insert (`reset_document_chunks`, citations first for FK) |
| New Redis pool per upload | Shared pool / app-state connection |
| Local filesystem only | Abstract object storage interface early (local now, S3/R2 later) |
| No re-ingest / delete path | Idempotent reprocess + cascade delete chunks + vectors |
| Extractors unproven | Smoke tests per `pdf` / `repo` / `audio` with fixtures |

**Effort:** M

---

### 8. Research run resilience

| Gap | Fix |
|---|---|
| WS disconnect → best-effort failed | Guaranteed status update; cancel in-flight agent if possible |
| Only `MAX_ITERATIONS=5` | Soft budget: max tool calls, max tokens, max wall clock |
| Errors always generic to client | Stable error codes (`retrieval_empty`, `model_exhausted`, `timeout`) |
| `langfuse_trace_id` discarded | Wire Langfuse spans around agent + retrieval (PRD N3) |
| Citations = all retrieved chunks | Dedupe by `chunk_id`; optionally map to answer spans later |
| No empty-corpus guard | If workspace has zero `done` docs, fail fast with clear message |

**Effort:** M

---

### 9. Model Gateway production behaviors

Already good: single interface, Groq → OpenRouter, tool parsing.

Still missing high-impact pieces:

- [x] **Timeouts + circuit breaker** per provider (avoid hanging WS forever)
  (per-provider timeout in litellm + 5-fails/30s breaker with cooldown, 2026-09-28)
- [x] **Retry only on idempotent/transient** errors with jitter
  (`src/shared/retry.py` — selective by exception type, exponential backoff + jitter, 2026-09-28)
- [x] **Token + cost accounting** on `ResearchRun` (even rough)
  (planner + HyDE + synthesis all metered; per-user daily budgets + `/usage`, 2026-09-28;
  workspace daily total surfaced on `/usage` as `workspace_today_tokens`, 2026-10-16)
- [x] **Structured refusal** when all providers fail (don’t half-stream)
  (typed `ProviderError`/`RateLimitError` with user-safe messages;
  SSE error-frame scan test, 2026-10-16)
- [x] **Provider health** in `/health`
  (`/readyz` advisory: circuit-breaker snapshot + embedding-version consistency, 2026-10-16)
- [x] Remove or gate `/test-llm` behind `APP_DEBUG`
  (route registered only when `APP_DEBUG=true`, 2026-10-16)

**Effort:** S–M

---

### 10. Database and schema quality

| Gap | Fix |
|---|---|
| No tsvector (P0 #3) | Migration + backfill |
| Embeddings not durable | Store embedding column or side table |
| `allowlist = all workspace chunk ids` loaded every query | Paginate / use SQL semi-join; cap pool size |
| No partial indexes | Index `documents(workspace_id, processing_status)`, `chunks(document_id)` |
| Enums + JSONB timestamps | Document conventions; consider proper stage history table if ops needs it |
| Connection pool defaults | Tune for Neon (`pool_size`, `max_overflow`, `pool_recycle`) |

**Effort:** M

---

### 11. Observability that operators can use

Logfire spans exist; Langfuse is configured but **not meaningfully used** in
the agent path (`langfuse_trace_id` is deleted).

**Minimum useful observability set**

| Signal | Why |
|---|---|
| Per-run: latency, iterations, citation count, provider used | Debug bad answers |
| Per-ingest: stage durations, chunk count, embed latency | Catch stuck jobs |
| Degraded-mode counters | Catch silent fallbacks |
| Error rate by endpoint | Ops |
| Langfuse trace id returned on answer payload (dev) | Deep dives |

Defer Prometheus/Grafana until volume exists (PRD Non-Goal) — but make
Langfuse **actually** record research runs now.

**Effort:** S–M

---

### 12. Security seams (without building full RBAC)

Full RBAC is deferred. Still do:

- Do not trust raw `X-Workspace-Id` forever without validation notes
- Tighten CORS for non-local origins
- Disable OpenAPI + `/test-llm` in production
- Sanitize filenames on upload (path traversal)
- Never log full document text / prompts to client channels (already a rule)
- Rate-limit upload + research (needs small ADR: slowapi / Redis token bucket)

**Effort:** S–M

---

## P2 — Architectural leverage (after core loop works)

### 13. Split “quality path” from “orchestration path”

Today the research agent is a single ReAct loop with one tool. That is correct
for MVP. When quality plateaus, invest in **measurement first**, then agents:

```text
Golden set (20–50 Qs)
  → retrieval metrics (recall@k, MRR)
  → answer faithfulness (manual or RAGAS later)
  → only then Critic / Planner specs
```

Building Critic before measuring Researcher failure modes wastes cycles
(`AGENTS.md` rule).

**Effort:** L (process + eval harness) · **When:** after P0 E2E green

---

### 14. Citation integrity beyond “retrieved = cited”

**Current pattern (good):** citation-at-retrieval — attach refs when chunks
are fetched.

**Still weak for enterprise trust**

- All retrieved chunks become citations, even unused ones
- No claim→span linking in answer text
- `source_ref` is coarse (`filename, chunk N`)
- UI may not open the exact passage

**Improvements**

1. Prompt model to emit `[n]` markers; only keep citations referenced in text
2. Store optional `answer_span` on `citations` (schema already contemplates it)
3. API to fetch chunk text by id for citation click-through
4. Integration test: every `[n]` in answer maps to a real chunk (runtime
   marker validator + unit tests added 2026-09-28; E2E form still open)

**Effort:** M

---

### 15. Retrieval architecture upgrades (incremental)

Only after baseline hybrid works:

| Upgrade | Signal to build |
|---|---|
| Query classification (skip HyDE for keyword queries) | HyDE hurts latency/quality on short queries |
| Metadata filters (doc type, date, filename) | Users ask “only in the PDF…” |
| Parent-document / small-to-big expansion | Answers need more context than chunk |
| MMR diversity | Redundant near-duplicate chunks |
| Dedicated cross-encoder service | Cosine-rerank plateaus |
| pgvector dual-write experiment | In-process ANN ops pain (pgvector is now the index) |

**Effort:** L · **Do not** jump to semantic cache first (PRD Non-Goal)

---

### 16. Worker / API process topology

**Today**

- FastAPI process + separate arq worker
- In-memory vector index per process
- Local disk uploads

**Target for managed deploy (Neon + Upstash + Render/Fly)**

```text
[Vercel web] → [API service] → [Postgres]
                     │              ↑
                     ├─ Redis/arq ──┤
                     ↓              │
              [Worker service] ─────┘
                     │
              [Embed/Rerank TEI]
```

- Shared embedding store or rebuild protocol (P0 #2)
- Object storage for raw files (API and worker may not share disk)
- Horizontal workers with job concurrency limits by source type
  (audio/PDF are CPU/GPU heavy)

**Effort:** L

---

### 17. Frontend productization (`apps/web`)

UI exists (upload, poll, WS ask, citations) but is still thin.

| Improvement | Why |
|---|---|
| Citation click → chunk passage modal | Closes the trust loop |
| Clear error surfaces for WS + failed jobs | Non-dev usability |
| Disable ask until ingest `done` | Prevent empty retrieval |
| Document list / history of runs | Basic product continuity |
| Env-based API URL + health banner | Deploy readiness |
| Extract components into `@repo/ui` | Monorepo payoff |
| Replace starter READMEs | Onboarding |

**Effort:** M

---

### 18. Monorepo / platform engineering

| Gap | Fix |
|---|---|
| No GitHub Actions / CI | `ruff`, `basedpyright`, `pytest`, `pnpm lint`, `pnpm check-types` |
| Python outside turbo task graph | Add turbo tasks or root scripts that `cd apps/api && uv run …` |
| No `Makefile` / `justfile` for common flows | `make api`, `make worker`, `make e2e` |
| `apps/docs` still starter template | Either real product docs or remove from critical path |
| Graph / AGENTS tooling stale risk | Document `graphify update` / code-review-graph rebuild in CONTRIBUTING |
| Secrets only in `.env` | `.env.example` complete + deployment secret map |

**Effort:** S–M · **Huge** for multi-contributor velocity

---

## P3 — Wait for signal (intentionally later)

Do **not** prioritize these over P0/P1 unless a metric demands it:

| Item | Why wait |
|---|---|
| Planner agent | Single-hop MVP doesn’t need decomposition yet |
| Critic / reflection | Need baseline failure rate first |
| Semantic cache | Needs query volume + invalidation design |
| Working / semantic memory | Single-shot loop doesn’t need it |
| MCP tools (web/GitHub/FS) | Expands trust boundary massively |
| Full RBAC / Vault | Single-tenant until second real user |
| LiteLLM multi-provider | Gateway already has two providers |
| Nightly RAGAS/DeepEval | Needs golden set from real usage |
| Voice UI | Built beyond the MVP bar (ADR-006): real-time STT + hosted Groq Orpheus TTS (amended 2026-10-16) |

When ready: write `docs/specs/{critic,planner,memory}.md` **before** code.

---

## Things easy to forget (checklist)

These often get skipped in agentic RAG builds:

### Correctness & data

- [x] **Embedding versioning** — model name + dim stored with vectors; refuse mixed dims
  (`chunks.embedding_model` provenance + `/readyz` consistency advisory, 2026-10-16)
- [ ] **Ingest idempotency** — re-upload same file shouldn’t duplicate silently
- [x] **Orphan cleanup** — delete document → delete chunks, vectors, jobs, files
  (`storage.delete_ref()` + delete-document cleanup + tests, 2026-10-16)
- [ ] **Clock / timezone** — already UTC-ish; keep it consistent in API responses
- [ ] **Empty retrieval UX** — “no documents searchable yet” vs “no evidence found”
- [ ] **Partial failure mid-pipeline** — failed after embed but before persist leaves orphans

### Distributed systems

- [x] **At-least-once arq jobs** — make ingest stages re-runnable
  (`reset_document_chunks` delete-before-insert; `GET /jobs/failed` → `POST /jobs/{id}/retry`, 2026-09-28)
- [x] **Poison messages** — permanent extract failures shouldn’t retry forever
  (DLQ surface + explicit retry; backoff retries only on transient failures)
- [ ] **Backpressure** — limit concurrent heavy jobs (whisper/docling)
- [x] **WS auth** — today open; plan token query param or cookie when auth lands
  (`?token=` accepted for browser WS handshakes; header preferred, 2026-10-16)
- [ ] **Request IDs** — propagate `X-Request-Id` through logs, jobs, traces

### LLM systems

- [x] **Prompt/version registry** — system prompts as versioned artifacts
  (`src/shared/prompts.py` + Langfuse stamps + regression tests, 2026-09-28)
- [x] **Tool argument validation** — reject empty/insane retrieval queries
  (pydantic-validated with raw-question fallback, 2026-09-28)
- [x] **Output size caps** — max answer tokens to protect UX and cost
  (`MAX_ANSWER_TOKENS` wired into synthesis, 2026-10-16)
- [x] **No CoT leakage** — add a test that scans WS frames for prompt fragments
  (`tests/research/test_sse_leakage.py` — stage vocabulary + safe error frames, 2026-10-16)
- [x] **Evaluation harness early** — even 10 hand-labeled questions pays off
  (retrieval harness + recorded-answer eval wired with gates, 2026-09-28;
  checked-in golden set still placeholder)

### Product / ops

- [ ] **Run history API** already partial — wire UI to `GET /runs/{id}`
- [ ] **Admin “rebuild vectors” endpoint** (debug-only)
- [x] **Disk usage monitoring** for `UPLOAD_DIR`
  (`/readyz` `upload_disk` advisory, 2026-10-16)
- [x] **Cost ceiling per workspace** (even soft logging)
  (per-user daily token budget + `/usage` incl. `workspace_today_tokens`, 2026-10-16)
- [x] **Incident playbook** — “embeddings down”, “Redis down”, “Neon cold start”
  (`docs/INCIDENT-PLAYBOOK.md`, 2026-10-16)

---

## Suggested 30 / 60 / 90 day plan

### Days 0–30 — Honest MVP

1. tsvector migration + FTS query fix  
2. Real embed/rerank; strict mode in non-dev  
3. Durable embeddings or rebuild protocol across API/worker  
4. Upload validation + shared Redis pool + health checks  
5. E2E smoke + GitHub Actions CI  
6. Langfuse actually tracing research runs  
7. Browser path verified (upload → cite)

**Exit criteria:** PRD success criteria true on a real PDF without manual DB surgery.

### Days 31–60 — Productize

1. Citation click-through + run history UI  
2. Ingest retries, reprocess, delete  
3. Rate limits, CORS, remove debug endpoints  
4. Deploy: web (Vercel) + API/worker (Render/Fly) + Neon + Upstash + TEI  
5. Cost/latency fields on runs; degraded-mode dashboards  
6. Small golden set (20 Qs) and manual scorecard

**Exit criteria:** A non-author can use the app; failures are diagnosable.

### Days 61–90 — Quality loop (only if metrics say so)

1. Spec + implement Critic **if** faithfulness issues dominate  
2. Query routing / metadata filters if retrieval miss patterns are clear  
3. Planner only for multi-hop failure cluster  
4. Nightly eval once golden set ≥ 50

**Exit criteria:** Measured quality gains, not architecture cosplay.

---

## Highest-ROI matrix

| Rank | Improvement | Priority | Effort | Why first |
|---|---|---|---|---|
| 1 | Fail loud on embed/rerank fallback | P0 | S | Stops fake success |
| 2 | tsvector + GIN | P0 | S | Real keyword search |
| 3 | Shared/durable vectors across processes | P0 | M | Correctness under worker split |
| 4 | Real Cohere embed/rerank path | P0 | M | Semantic quality |
| 5 | E2E + CI | P0 | M | Confidence to ship |
| 6 | Deep health + upload limits + retries | P1 | M | Survives first users |
| 7 | Langfuse on agent path | P1 | S | Debug answers |
| 8 | Citation UI + empty-state guards | P1 | S | Trust |
| 9 | Object storage abstraction | P1 | M | Multi-node deploy |
| 10 | Golden-set eval harness | P2 | M | Guides Phase 2 agents |

---

## Anti-goals (do not do next)

These feel productive but usually reduce momentum for *this* repo:

1. Building Planner/Critic before E2E citations work  
2. Adding more model providers before timeouts/cost tracking exist  
3. Rewriting the monorepo structure  
4. Replacing LangGraph / FastAPI / Next without an ADR-level reason  
5. Perfect multi-tenant RBAC before a second tenant exists  
6. Semantic cache before query volume and invalidation needs appear  
7. “Just use a mega-agent framework” rewrites that abandon citation-at-retrieval

---

## Related documents

| Doc | Role |
|---|---|
| `docs/PRD.md` | MVP scope and Non-Goals |
| `docs/REMAINING.md` | Build vs remaining feature matrix |
| `ROADMAP.md` | Step-by-step “get it testable” plan |
| `docs/schema.md` | Data model + Postgres-authoritative rule |
| `docs/specs/*` | Component contracts |
| `docs/adr/*` | Locked tech choices |
| `docs/ux.md` | Progress vocabulary + citation UX |
| `docs/conventions.md` | Structure and approved libraries |

---

## Bottom line

You already have the **right MVP architecture**: feature modules, Model
Gateway, citation-at-retrieval, async ingest, hybrid retrieval sketch, thin
web client.

The impactful engineering work is to **remove lies from the happy path**
(silent fallbacks, process-local vectors, unproven E2E), then **instrument
and harden**, then **only add multi-agent complexity when metrics demand it**.

> Ship a boring, correct, cited answer loop first.  
> Fancy agents on top of random embeddings are theater.
