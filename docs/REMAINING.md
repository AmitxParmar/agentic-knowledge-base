# Remaining Work — Agentic Research Workspace

> Snapshot of what is built vs what is left, derived from
> `docs/latest-architecture.html` (V1 design), `docs/PRD.md` (MVP boundary),
> `ROADMAP.md`, specs, and the current `apps/` code.
>
> Last updated: 2026-08-09

## Status legend

| Mark | Meaning |
|---|---|
| **Done** | Code exists and is wired |
| **Partial** | Scaffolded, but incomplete / fallback / not proven end-to-end |
| **Remaining** | Not built, or still needs operational verification |
| **Deferred** | Explicitly out of MVP (Phase 2+ per PRD Non-Goals) |

## How to read this document

- **MVP path:** upload → arq ingestion → Postgres + vectors → question over
  SSE (AG-UI) → Research Agent → hybrid retrieval → cited answer.
- **Not in MVP:** Planner, Critic, semantic cache, MCP tools, full security
  zone, nightly eval, multi-agent live trajectory UI.
- Rule from `AGENTS.md`: do not build deferred V1 features without a
  production signal and a spec under `docs/specs/`.

---

## Architecture zones vs implementation

| Zone | MVP target | Today |
|---|---|---|
| Clients | Minimal web | Partial Next.js UI |
| API Gateway | FastAPI REST + SSE (AG-UI) | Done (no input guard / semantic cache) |
| Retrieval | Hybrid + rerank | Partial (fallbacks, no tsv GIN) |
| Orchestration | 1 Research Agent | Done (no Planner / Critic) |
| Memory | — | Deferred |
| Storage | PG + vectors + FS | Partial (tsv / Turbovec gaps) |
| Ingestion | arq 6-stage | Code done; E2E unproven |
| Model Gateway | Swappable | Done (Groq → OpenRouter) |
| MCP tools | — | Deferred |
| Observability | Langfuse traces | Wired; needs live config |
| Security | Auth stub | Stub only |
| Deploy | Local / managed | Neon + Upstash intended; no IaC |

---

## Suggested order

```text
1. DB: upgrade + seed + tsvector migration          ← unblocks BM25 quality
2. Embed/rerank real endpoints (kill hash fallback) ← unblocks meaningful search
3. Worker + upload PDF E2E                          ← unblocks retrieval
4. retrieve() smoke + research agent + SSE          ← MVP success criteria (verified 2026-08-09)
5. Browser path via apps/web                        ← non-dev testing
6. Hardening (health, limits, retries)              ← before real users
7. Only then: Critic → Planner → cache → RBAC       ← V1 diagram features
```

---

## A. Clients

| Item | Status | Notes |
|---|---|---|
| Minimal Next.js chat + upload (`apps/web`) | Partial / Done | Upload, job poll, SSE Q&A (TanStack AI), citations UI exist |
| Live multi-agent trajectory UI | Deferred | `ux.md`: MVP shows stage names only |
| Voice UI | Remaining | Architecture shows “Chat / Voice”; not in MVP |
| API / CLI client polish | Partial | REST + SSE exist; no dedicated CLI package |
| `apps/docs` product docs site | Remaining | Still Turborepo starter template |
| Root `README` product docs | Remaining | Still generic Turborepo starter |

### Checklist

- [ ] Verify upload → poll → ask → cite E2E in the browser
- [ ] Error surfaces for SSE `RUN_ERROR` and failed ingestion
- [ ] Citation click → show source chunk passage
- [ ] Deploy Next.js (Vercel) when backend is stable

---

## B. API Gateway

| Item | Status | Notes |
|---|---|---|
| FastAPI factory, CORS, `/health` | Done | `app/main.py` |
| Ingestion + research routers mounted | Done | |
| Auth (JWT / multi-user) | Partial | `auth/stub.py` single-tenant only |
| Rate limiting | Remaining | ROADMAP F2; needs ADR |
| Input Guardrail (LLM Guard) | Deferred | PRD Non-Goals |
| Semantic Cache Check (Redis vector) | Deferred | PRD Non-Goals |
| Expanded `/health` (DB + Redis + BGE) | Remaining | F2 |

### Checklist

- [ ] Confirm migrations applied on Neon and seed user/workspace
- [ ] Health checks for dependencies
- [ ] Tighten CORS / remove `/test-llm` for prod

---

## C. Retrieval Engine

| Item | Status | Notes |
|---|---|---|
| HyDE query rewrite | Done | Via Model Gateway |
| Hybrid dense + BM25 + RRF | Partial | BM25 uses `to_tsvector` on the fly — no persisted `tsv` + GIN in migration |
| Workspace ID allowlist filter | Done | In hybrid search path |
| Cross-encoder rerank (BGE-Reranker) | Partial | Code path exists; falls back when LM Studio / TEI down |
| BGE-M3 embeddings | Partial | Real client + hash embedding fallback if LM Studio unreachable |
| Turbovec ANN | Partial | Wrapper + numpy cosine fallback if turbovec missing |
| Rebuild index from Postgres on startup | Done | Lifespan in `main.py` |

### Checklist (critical for real quality)

- [ ] Migration: `chunks.tsv` + GIN + trigger (ROADMAP Step 4; missing today)
- [ ] Run real BGE embed + rerank services (TEI or LM Studio); stop relying on hash/uniform fallbacks
- [ ] Install/verify Turbovec in the runtime used for demos
- [ ] Integration proof: ranked results with real `source_ref` / `chunk_id`

---

## D. Multi-agent orchestration

| Item | Status | Notes |
|---|---|---|
| LangGraph Research Agent (ReAct) | Done | `src/research/agent.py` |
| Citation-at-retrieval | Done | Spec + integration test scaffolding |
| Iteration bound (mini circuit breaker) | Partial | `MAX_ITERATIONS = 5` only |
| SSE (AG-UI) progress stages | Done | Must match `ux.md` vocabulary |
| Planner Agent | Deferred | Needs `docs/specs/planner.md` first |
| Critic + reflection loop | Deferred | Needs `docs/specs/critic.md` first |
| Plan Cache (APC) | Deferred | Depends on Planner |
| Full Circuit Breaker (cost, reflections) | Deferred | After Critic |

### Checklist (MVP ops)

- [x] Prove agent E2E: answer + ≥1 citation + `research_runs` / `citations` rows — verified 2026-08-09 (SSE, 8 citations persisted)
- [x] Prove SSE stage order and no CoT/prompt leakage — verified 2026-08-09
- [ ] Disconnect mid-run → `failed` status

---

## E. Model routing & tools

| Item | Status | Notes |
|---|---|---|
| Model Gateway abstraction | Done | ADR-003; `complete` / `complete_with_tools` |
| Provider chain | Partial | Groq → OpenRouter (not LiteLLM / Ollama as HTML labels) |
| LiteLLM multi-provider | Deferred | PRD + F8 |
| MCP Tool Layer (FS / GitHub / web) | Deferred | MVP tool = retrieval only |

### Checklist

- [ ] Keys in `.env` validated (`/test-llm` or gateway tests)
- [ ] Document actual stack vs architecture diagram (Groq/OpenRouter vs LiteLLM/Ollama)

---

## F. Memory

| Item | Status | Notes |
|---|---|---|
| Working Memory (Redis session trajectory) | Deferred | Redis used for arq only |
| Conversation Summaries | Deferred | `schema.md` deferred entity |
| Semantic Memory | Deferred | `schema.md` deferred entity |

Nothing required for single-shot MVP.

---

## G. Storage

| Item | Status | Notes |
|---|---|---|
| PostgreSQL ORM models | Done | users, workspaces, documents, jobs, chunks, runs, citations |
| Alembic initial migration | Partial | Tables exist; no tsvector infrastructure |
| Seed script | Done | `scripts/seed.py` |
| Local raw file storage | Done | `UPLOAD_DIR` pattern |
| Turbovec as durable vector store | Partial | Rebuildable from PG in principle; often numpy in dev |

### Checklist

- [ ] `alembic upgrade head` on target DB
- [ ] Seed + FK integrity
- [ ] Confirm 7 tables + citations; add `tsv` migration
- [ ] Neon (prod) / local Postgres decision locked in env

---

## H. Ingestion pipeline

| Item | Status | Notes |
|---|---|---|
| Upload API + job status | Done | |
| arq worker entry | Done | `app/workers.py` / WorkerSettings |
| Docling / whisper / tree-sitter extractors | Partial | Wrappers present; heavy deps must be installed and tested per type |
| Chonkie semantic + code chunking | Done (code) | Needs real-file verification |
| Dedicated Metadata Extractor stage | Partial | Metadata fields on chunks; not a rich author/date/category service as in HTML |
| Embed + persist stages | Done (code) | Depends on embedder quality |
| Ingestion progress to client | Partial | Job poll stages; ensure UX strings match `ux.md` |
| Retry (3×) on transient failure | Remaining | F2 |
| File size / type validation | Remaining | F2 |

### Checklist

- [ ] PDF E2E &lt; 60s → `done` + non-zero chunks
- [ ] Repo zip / git URL path smoke
- [ ] Audio path smoke
- [ ] arq worker + Redis (`rediss://` Upstash) stable

---

## I. Output guardrail & observability

| Item | Status | Notes |
|---|---|---|
| Observability setup (Logfire + Langfuse wire-up) | Partial | `src/observability/setup.py`; needs tokens + real traces |
| Output Guardrail (Guardrails AI) | Deferred | PRD |
| RAGAS + DeepEval nightly | Deferred | F10 / needs golden set |
| Prometheus + Grafana | Deferred | F10 |

### Checklist (MVP-adjacent)

- [ ] Langfuse shows full run traces
- [ ] Logfire in cloud for shared env
- [ ] Optional: cost estimate on `ResearchRun` (F3)

---

## J. Security & access control

| Item | Status | Notes |
|---|---|---|
| Workspace-scoped retrieval filter | Partial | Query filter only; not hard multi-tenant RBAC |
| RBAC | Deferred | F9 |
| Scoped Retrieval as security boundary | Deferred | F9 |
| Secret management (Vault) | Partial | Env-based only |
| Tool Guardrails | Deferred | No MCP tools yet |

---

## K. Deployment & runtime

| Item | Status | Notes |
|---|---|---|
| Local monorepo (pnpm + uv) | Done | Scaffold |
| Docker-compose for PG/Redis | Skipped by design | ROADMAP: use Neon + Upstash |
| Vercel frontend | Remaining | |
| Render API + workers | Remaining | |
| Docker images for heavy ingestion models | Remaining | |
| BGE TEI containers | Remaining | ROADMAP Step 7 |

---

## L. Core pipeline ops (get it testable)

Highest priority. Code is largely written; ops and proof are not.

| Step | Status |
|---|---|
| 1. Fix import paths / worker location | Done (codebase uses `app.*` / `src.*`) |
| 2. Config files (`alembic.ini`, pyright) | Mostly done — confirm alembic CLI |
| 3. Services (Neon + Redis URLs in `.env`) | Remaining to verify |
| 4. Migration + **tsvector** | Partial — tables yes, tsv no |
| 5. Seed | Script exists — run not verified |
| 6. Model gateway smoke | Remaining to verify |
| 7. BGE services | Remaining |
| 8. Ingestion E2E | Remaining |
| 9. Retrieval script/tests | Remaining |
| 10. Research agent E2E | Remaining |
| 11. SSE (AG-UI) contract | Done — verified 2026-08-09 |
| 12. ruff + basedpyright + pytest green | Remaining to verify |

### Definition of Done (still open)

- [ ] PDF upload → `done` without manual steps
- [x] Question → cited answer over SSE — verified 2026-08-09
- [ ] ≥1 citation with usable `source_ref`
- [ ] Progress events use only `ux.md` strings
- [ ] Lint + typecheck clean

---

## M. Phase 2+ (architecture HTML, explicitly deferred)

Do not build without a metric / PRD justification (`AGENTS.md`).

- [ ] **F4** Critic + reflection (requires `docs/specs/critic.md`)
- [ ] **F5** Planner + plan cache (requires `docs/specs/planner.md`)
- [ ] **F6** Semantic cache
- [ ] **F7** Working / semantic / conversation memory
- [ ] **F8** LiteLLM multi-provider
- [ ] **F9** Real auth + RBAC + guardrails
- [ ] **F10** Golden-set eval + Prometheus / Grafana
- [ ] Full circuit breaker (cost + reflection caps)
- [ ] MCP tools (filesystem, GitHub, web search)

---

## High-level architecture (V1)

Ten zones from `docs/latest-architecture.html`. MVP ships a thin vertical
slice: Clients → Gateway → Retrieval → single Research Agent → Storage +
Ingestion.

```mermaid
flowchart TB
  subgraph Clients
    CHAT["Chat / Voice UI<br/>Next.js · SSE (AG-UI)"]
    API["API / CLI Client<br/>REST · Bearer"]
  end

  subgraph Gateway["API Gateway"]
    FA["FastAPI"]
    IG["Input Guardrail"]
    SC["Semantic Cache"]
  end

  subgraph Retrieval["Retrieval Engine"]
    HYDE["Query Rewrite · HyDE"]
    HYB["Hybrid Search + RRF"]
    RER["Cross-Encoder Rerank"]
  end

  subgraph Agents["Multi-Agent Orchestration"]
    LG["LangGraph Runtime"]
    CB["Circuit Breaker"]
    PL["Planner"]
    PC["Plan Cache"]
    RA["Research Agent"]
    CR["Critic"]
  end

  subgraph Memory
    WM["Working Memory · Redis"]
    CS["Conversation Summaries"]
    SM["Semantic Memory"]
  end

  subgraph Storage
    PG[("PostgreSQL")]
    TV[("Turbovec")]
    FS[("PDF / raw storage")]
  end

  subgraph Models["Model Routing & Tools"]
    MG["Model Gateway"]
    MCP["MCP Tool Layer"]
  end

  subgraph Ingest["Ingestion Pipeline"]
    Q["arq workers"]
    DOC["Docling"]
    WH["faster-whisper"]
    CODE["tree-sitter + gitingest"]
    CHK["Chonkie"]
    META["Metadata Extractor"]
    EMB["BGE-M3"]
  end

  subgraph Guard["Output Guardrail & Observability"]
    OG["Output Guardrail"]
    LF["Langfuse"]
    RG["RAGAS + DeepEval"]
    PGRAF["Prometheus + Grafana"]
  end

  subgraph Sec["Security & Access"]
    RBAC["RBAC"]
    SCOPED["Scoped Retrieval"]
    SECRETS["Secret Mgmt"]
    TG["Tool Guardrails"]
  end

  subgraph Deploy["Deployment"]
    VERCEL["Vercel"]
    RENDER["Render"]
    UPSTASH["Upstash"]
    NEON["Neon"]
    DOCKER["Docker"]
  end

  CHAT --> FA
  API --> FA
  FA --> IG --> SC
  SC -->|hit| CHAT
  SC -->|miss| CB
  LG --> CB --> PL --> RA
  PC -.-> PL
  PC -.-> RA
  RA --> HYDE --> HYB
  HYB --> TV
  HYB --> PG
  HYB --> RER --> RA
  RA --> CR
  CR -->|evidence gap| RA
  CR -->|ok| OG --> CHAT
  PL & RA & CR --> MG
  RA --> MCP
  RA -.-> WM
  RA --> CS --> SM
  API -.-> Q
  Q --> DOC & WH & CODE --> CHK --> META --> EMB
  EMB --> TV & PG
  Q --> FS
  RA & CR --> LF --> PGRAF
  RG -.-> RA & CR
  IG -.-> RBAC
  SCOPED -.-> HYB
  SECRETS -.-> MG
  TG -.-> MCP
```

---

## Low-level: ingestion

```mermaid
sequenceDiagram
  participant UI as Next.js / curl
  participant API as FastAPI ingestion router
  participant FS as Local upload dir
  participant Redis as Redis arq
  participant W as arq worker
  participant X as Extractors
  participant C as Chonkie chunker
  participant E as Embedder BGE-M3
  participant PG as PostgreSQL
  participant TV as Turbovec / numpy fallback

  UI->>API: POST /api/ingestion/upload
  API->>FS: write raw file
  API->>PG: documents + ingestion_jobs (queued)
  API->>Redis: enqueue run_ingestion_job
  API-->>UI: document_id, job_id
  W->>PG: stage = extracting
  W->>X: extract(path, source_type)
  W->>PG: stage = chunking
  W->>C: chunk_document()
  W->>PG: stage = embedding
  W->>E: embed_texts(chunks)
  W->>PG: INSERT chunks (+ metadata)
  W->>TV: upsert vectors by chunk_id
  W->>PG: stage = done / failed
  UI->>API: GET /api/ingestion/jobs/{id} (poll stages)
```

---

## Low-level: research run (MVP)

```mermaid
sequenceDiagram
  participant UI as Next.js (TanStack useChat)
  participant API as POST /api/research/chat (SSE)
  participant Auth as auth stub
  participant AG as LangGraph Research Agent
  participant MG as Model Gateway
  participant RET as retrieval pipeline
  participant PG as PostgreSQL
  participant TV as Turbovec
  participant LF as Langfuse / Logfire

  UI->>API: POST {question, threadId}
  API-->>UI: RUN_STARTED / TEXT_MESSAGE_START
  API->>Auth: workspace_id / user_id
  API->>PG: research_runs (running)
  AG->>MG: ReAct (tools: retrieve_evidence)
  AG->>RET: retrieve(question, workspace_id)
  RET->>MG: HyDE expand query
  RET->>PG: BM25 / FTS + workspace allowlist
  RET->>TV: dense ANN on allowlist
  RET->>RET: RRF merge
  RET->>RET: rerank
  RET-->>AG: RetrievedChunk[] + source_ref
  Note over AG: citations attached at retrieval time
  loop progress
    API-->>UI: CUSTOM stage (Searching → Finalizing)
  end
  AG->>MG: draft final answer
  AG->>PG: citations rows + answer
  API-->>UI: CUSTOM citations
  API-->>UI: TEXT_MESSAGE_CONTENT (answer)
  API-->>UI: TEXT_MESSAGE_END / RUN_FINISHED
  AG-->>LF: spans / traces
```

---

## Low-level: V1 multi-agent (not built yet)

```mermaid
flowchart LR
  Q[User question] --> IG[Input Guard]
  IG --> CACHE{Semantic cache<br/>cosine ≥ 0.85?}
  CACHE -->|hit| OUT[Stream answer]
  CACHE -->|miss| CB[Circuit Breaker]
  CB --> PL[Planner]
  PL --> APC{Plan cache hit?}
  APC -->|yes| RA[Researcher]
  APC -->|no| PL
  PL --> RA
  RA --> HYDE[HyDE]
  HYDE --> HYB[Dense ⊕ BM25 + RRF]
  HYB --> RR[Rerank]
  RR --> RA
  RA --> MCP[MCP tools]
  RA --> CR[Critic]
  CR -->|gap| RA
  CR -->|ok| OG[Output Guard]
  OG --> OUT
  OG --> CACHE
```

---

## Related docs

| Doc | Role |
|---|---|
| `docs/latest-architecture.html` | Interactive V1 architecture (source of truth for design) |
| `docs/PRD.md` | MVP scope and Non-Goals |
| `ROADMAP.md` | Step-by-step “get it testable” plan + Future Plan |
| `docs/schema.md` | Conceptual data model + deferred entities |
| `docs/specs/*` | Component contracts (ingestion, retrieval, researcher) |
| `docs/ux.md` | Client progress vocabulary and citation display rules |
| `docs/adr/*` | Locked tech decisions (LangGraph, Turbovec, Model Gateway) |

---

## Bottom line

Scaffolding covers most of the **MVP slice** of the architecture (ingest →
hybrid retrieve → single ReAct researcher → citations + thin web UI).

What remains is less greenfield modules and more:

1. **Make the core pipeline real** — DB/tsv, real embeddings, E2E proofs, remove silent fallbacks
2. **Productize** — frontend polish, hardening, deploy
3. **Unlock V1 multi-agent / cache / security / eval** only when usage justifies them
