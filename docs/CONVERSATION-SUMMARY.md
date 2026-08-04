# Conversation summary — architecture, remaining work, ops

> Session notes capturing design decisions, gaps, and recommendations from a walkthrough of the Agentic Research Workspace (enterprise-agentic-knowledgebase).  
> Related artifacts produced in-session: [`REMAINING.md`](REMAINING.md), root [`README.md`](../README.md).

---

## What this project is

**Yes — it is an agentic RAG knowledge base.**

| Layer | Meaning |
| --- | --- |
| **Knowledge base** | Upload PDF / repo / audio → extract → chunk → embed → Postgres + vectors |
| **RAG** | HyDE → hybrid search (dense + BM25 + RRF) → rerank → cite source chunks |
| **Agentic** | LangGraph **Research Agent** (ReAct): reason → retrieve → answer under an iteration cap |

Product name in docs: **Agentic Research Workspace**. MVP is a **single-agent** slice of the frozen V1 multi-agent design (Planner, Critic, semantic cache, MCP tools are deferred per `PRD.md`).

---

## Architecture review (from `docs/` + `latest-architecture.html`)

V1 zones (full design): Clients → API Gateway → Retrieval → Multi-Agent Orchestration → Memory → Storage → Ingestion → Guardrails/Observability → Security → Deployment.

**MVP vertical slice that exists in code:**

```text
Upload → arq ingestion → Postgres + vectors
     → WebSocket question → Research Agent → hybrid retrieval → cited answer
```

Interactive diagram: [`docs/latest-architecture.html`](latest-architecture.html).  
High/low-level Mermaid diagrams also live in the root [`README.md`](../README.md).

---

## Remaining work (categorized)

Full checklist: [`docs/REMAINING.md`](REMAINING.md). Snapshot:

| Zone | Status |
| --- | --- |
| Clients (Next.js thin UI) | Partial |
| FastAPI + ingestion/research routers | Done (code) |
| Hybrid retrieval | Partial (fallbacks; no persisted `tsv` GIN) |
| Research Agent (LangGraph) | Done (code) |
| Model Gateway (Groq → OpenRouter) | Done |
| Planner / Critic / plan cache | Deferred |
| Semantic cache / memory / MCP | Deferred |
| Auth | Stub only |
| E2E “definition of done” | Still open (ops/proof) |

**Practical order to finish core:**

1. DB seed + **tsvector** migration  
2. Real BGE embed/rerank (kill silent hash/uniform fallbacks)  
3. Worker + PDF ingestion E2E  
4. Retrieval + agent + WebSocket proof  
5. Browser path via `apps/web`  
6. Hardening — only then Critic → Planner → cache → RBAC  

---

## Token streaming

**Not implemented today.** Gateway uses non-stream `chat.completions.create()`; WebSocket sends one full `answer` blob after progress stages.

**Recommended design (same WebSocket):**

| Event | Role |
| --- | --- |
| `progress` | Fixed `ux.md` stages only (keep as-is) |
| `token` | Stream final answer deltas only |
| `answer` | Full text + citations (canonical) |
| `done` / `error` | Terminal |

- Stream **only final draft** generation — not tool-call loops (avoids leaking tool payloads; `ux.md` forbids CoT/tool dumps).  
- Fix stage order: emit **Generating report...** *before* the final LLM call (today it often fires after).  
- Add `stream_complete()` in Model Gateway; `emit_token()` in progress helpers; optional `token_callback` on the agent.

**Progress messages:** keep `stage_callback → emit(ws, ResearchStage)`. Do not invent free-form status strings.

---

## Testing clients: `wscat` vs scripts

Working smoke path:

```bash
npx wscat -c ws://127.0.0.1:8000/api/research/ws \
  -H "x-workspace-id: 00000000-0000-0000-0000-000000000001"
# then: {"question":"..."}
```

Also used: `apps/api/scratch_test.py` (upload → poll job → WS chat).

| Client | Use for |
| --- | --- |
| **wscat** | Manual “is WS alive?” / inspect messages |
| **scratch_test.py** | Full upload → ask smoke |
| **pytest + websockets** | CI contract (order, no CoT leakage) |
| **apps/web** | Product UX |

**Caveat:** seed/stub workspace is typically `…0001` (user `…0002`). Using `…0000` can yield empty retrieval. Align clients with seed.

---

## Current API surface (MVP)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/ingestion/upload` | Upload + enqueue arq |
| `GET` | `/api/ingestion/jobs/{id}` | Poll ingestion |
| `WS` | `/api/research/ws` | Progress → answer |
| `GET` | `/api/research/runs/{id}` | Fetch completed run |
| `GET` | `/health` | Liveness only |

Gaps for a product API: document list/delete, readiness probe, rate limits, real auth, versioning, reconnect-friendly runs.

---

## Turbovec

- **Not a separate server** — library/index **in the FastAPI process**.  
- Postgres is **source of truth**; vectors rebuild from PG on startup.  
- **Dev:** numpy fallback OK for smoke only.  
- **Prod/demos:** fail loudly if Turbovec missing; no silent numpy.  
- Multi-API-replica needs care (per-process index). Don’t swap to another vector DB without an ADR.

---

## Process / server count

**Minimum app processes: 2**

| Process | Required? |
| --- | --- |
| FastAPI | Yes |
| arq worker | Yes |
| Turbovec | No (in-process) |
| Postgres | Managed (e.g. Neon) |
| Redis | Managed (e.g. Upstash) |
| BGE embed/rerank | Optional +1–2 HTTP services |

---

## Hosting

**Can it run on Render?** Yes **if paid/always-on** web + always-on worker. **Free / spin-down tiers are a bad fit** (worker dies, cold starts, WS flakes, Turbovec rebuild on wake).

**Recommended split:**

```text
Vercel     → Next.js
Neon       → Postgres
Upstash    → Redis
Fly / Railway / paid Render / VPS
           → FastAPI + arq worker
Optional   → BGE / heavy ingestion on a dedicated box
```

---

## Next phase (after core loop works)

**Not** multi-agent first. **Production-grade single-agent RAG:**

1. Real retrieval quality (BGE, Turbovec, tsv)  
2. Token streaming  
3. Web UX polish  
4. Hardening (`/readyz`, limits, retries, E2E test)  
5. Live Langfuse/Logfire traces  

**After that (with metrics + specs):** Critic → Planner → semantic cache → memory → RBAC → eval.

Sprint-shaped goal: *PDF in → streamed cited answer out → no silent fallbacks → green E2E.*

---

## Production improvements (condensed)

| Priority | Themes |
| --- | --- |
| P0 | Streaming, real embed/rerank, tsv, workspace consistency, cost/iteration caps, citation-at-retrieval |
| P1 | API versioning, document CRUD, scoped job/run access, shared Redis pool, JWT auth |
| P2 | Critic/Planner only after measuring failures; eval set before quality agents |
| P3 | Always-on deploy; careful multi-instance + Turbovec |
| P4 | Readiness, latency/citation metrics, alerts on ingestion failures |

---

## Artifacts written this conversation

| File | Content |
| --- | --- |
| [`docs/REMAINING.md`](REMAINING.md) | Categorized remaining checklist + architecture diagrams |
| [`README.md`](../README.md) | Project overview + high/low-level Mermaid diagrams (replaced Turborepo starter) |
| [`docs/CONVERSATION-SUMMARY.md`](CONVERSATION-SUMMARY.md) | This summary |

---

## Bottom line

Scaffolding covers most of the **MVP agentic RAG path**. What’s left is less greenfield agents and more: **make retrieval real, prove E2E, stream answers, harden, host with always-on API + worker**, then unlock V1 multi-agent features only when usage justifies them.
