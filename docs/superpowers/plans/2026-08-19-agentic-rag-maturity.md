# Agentic RAG Platform — Maturity Plan

> Principal-level architecture review and evolution roadmap for the Agentic
> Research Workspace: from strong MVP to production-grade Agentic RAG platform.
>
> Status: Planning. Not yet implemented.

---

## 1. Current architecture assessment

### What is already strong

- **The skeleton is real, not a toy.** FastAPI + LangGraph single-agent + hybrid retrieval (pgvector dense + Postgres FTS + RRF + Cohere rerank + HyDE) + arq workers + Redis + R2 + logfire/langfuse. Every tier exists end-to-end: upload → async ingestion → chunk → embed → search → agent → citations → UI.
- **Discipline in docs.** ADRs (001 LangGraph, 002 pgvector, 003 model gateway, 005 AG-UI, 006 voice, 007 semantic cache), specs per feature, PRD with explicit Non-Goals.
- **Graceful degradation is a habit.** Model gateway fallback chain (Groq → OpenRouter), Redis-down → open (rate limit + semantic cache return miss), checkpoint down → run without saver, insufficient-evidence refusal hard-coded so the model can't fabricate.
- **Citations survive the pipeline** — citation rows written at retrieval time, carried through `AgentResult`, replayed from the semantic cache, rendered in UI with `[n]` markers.
- **Feature-first folder structure** (`src/{research,retrieval,ingestion,...}`), no `services/`/`utils/` soup.
- **Cost metering started** — `token_count` on runs; semantic cache exists (flag-off) as the biggest cost lever already scoped.

### What is still MVP-level

- **Auth is a stub** (`src/auth/stub.py`) — `get_user_id`/`get_workspace_id` are placeholders. Single-tenant reality.
- **One agent, one tool.** ReAct loop with retrieval only. No Planner/Critic/MCP (deliberately deferred, but that's the whole thesis of the V1→V2 story).
- **Semantic cache is feature-flagged off.** Document-change invalidation and hit-rate metrics are now implemented (ADR-007 amended); still question-keyed only — multi-turn context ignored, recovered by threshold + TTL + invalidation.
- **No evaluation system at all** — no golden set, no offline metrics, no regression gate.
- **No RBAC/scoped retrieval, no guardrails, no prompt-injection defenses** — retrieval is workspace-scoped only because there's one tenant.
- **Tests exist but are thin** — no coverage for most agent paths; the pipeline's real behavior (rerank effectiveness, citation correctness) has no regression harness.
- **Worker infra is minimal** — one arq pool, in-process semaphores, no DLQ, no retry policies on jobs.
- **Frontend conversation/memory** — threads exist (`conversation_threads`, runs linked), but no real memory design beyond last-question history passed to the agent.

### Architectural weaknesses

1. **The agent is a monolith-in-a-loop.** `research/agent.py` (547 lines) mixes prompt, loop policy, tool definition, and synthesis. Extending toward planner/critic/verification means refactoring it into a composed graph *before* adding capabilities.
2. **No explicit context budget.** No token budgeting for retrieved chunks (lost-in-the-middle will bite as chunk counts grow), no context compression, no chunk-order strategy.
3. **No idempotency on the agent side.** Run retries on partial failure can duplicate work; `content_hash` dedup exists for ingestion only.
4. **Observability spans exist; dashboards/alerting don't.** No SLO dashboard, no cost-per-question view, no per-stage latency breakdown surfaced anywhere.
5. **Timeouts are uneven.** `PDF_PARSE_TIMEOUT` exists for extraction; LLM timeouts exist in the gateway; retrieval/rerank/embed timeouts are not uniformly budgeted, and there's no overall request budget.
6. **Memory is implicit.** "History" is raw messages pushed into the prompt with no compaction, no summarization, no cap.

### Missing capabilities (grouped)

| Area | Missing |
|---|---|
| Eval | Golden dataset, offline metrics, CI regression gate, rerank-vs-norank verification |
| Auth/RBAC | Real identity, workspace membership, per-tool authorization |
| Memory | Session memory, summarization, compaction, semantic/episodic memory |
| Reliability | Circuit breakers on providers, per-request budgets, DLQ, structured retries on ingestion jobs |
| Security | Prompt-injection defense, document sanitization, SSRF guard on URL tools, secrets handling |
| Ops | Dashboards, alerts, load test, capacity plan |

---

## 2. Maturity roadmap

```
V1 (current) ──► V2 ──► V3 ──► Production
single agent    multi-node    multi-agent    platform
ReAct + RAG     composed      planner/critic SaaS-ready
                graph         + memory
```

**V2 — "Composed pipeline" (weeks 1–6).** Turn the monolith loop into a **LangGraph pipeline with nodes, not agents**: `plan → retrieve → verify → synthesize`, all sharing one model budget, where "plan/critic" are **LangGraph nodes with cheap models**, not new agents. Add evaluation infrastructure (golden set + offline metrics) *in parallel* — you cannot tune V3 without it. Flip the semantic cache on (document-change invalidation + hit-rate metrics already shipped, ADR-007 amended). Add real auth (at least JWT + workspace membership).

- *Why:* nodes are deterministic, testable, cheaper than agents; eval must exist before agents multiply.
- *Don't add yet:* multi-agent debate, memory layers, tool gateway.

**V3 — "Agentic" (weeks 7–10).** Promote the pipeline into a **Planner-driven graph with specialized agents only where LLM judgment is the point**: Planner (task decomposition), Researcher (ReAct loop, now a *node*), Critic/Verifier (cheap-model node), Synthesizer (a node). Introduce the **tool gateway** (MCP) with web search + URL fetch as first tools, plus memory: session summary + semantic memory. Add guardrails (input/output), prompt-injection defense on retrieved content, RBAC-scoped retrieval.

- *Don't add yet:* multi-tenant billing, autonomous long-horizon tasks, agent teams.

**Production — platform hardening.** Real auth with roles, rate limiting per workspace, cost dashboards + budgets, load testing, autoscaling workers, DLQ + dead-letter reprocessing, SLO alerting, security review (SSRF, injection), multi-tenant isolation at the data layer.

---

## 3. Advanced agent architecture — avoid agent-ification

Rule: **make it a node unless the task needs judgment, memory of its own intent, or tool authority.**

| Component | Form | Why |
|---|---|---|
| Planner | **LangGraph node** (emits a plan structure via cheap model + JSON schema) | A plan is data, not an agent. Validate with Pydantic, fall back to single-step plan on parse failure |
| Researcher | **Agent** (existing ReAct loop, promoted to a node) | Needs tools + iteration — genuinely agentic |
| Retriever | **Deterministic service** (pipeline) | Never an LLM. Query analysis (rewrite/decompose) is a cheap-model *pre-node* |
| Tool-use agent | **Agent** (ReAct with tool gateway) | Distinct authority boundary + permission context |
| Critic/Verifier | **Node with cheap model** doing one pass: faithfulness + citation checks | Verification is a bounded judgment; separate agent = latency + cost + debate overengineering |
| Synthesizer | **Node** (main model) | One grounded generation pass |
| Citation verifier | **Deterministic service** (span extraction + chunk grounding) | Rule-based where possible; LLM only for fuzzy spans |
| Memory writer | **Node / event** (post-run summarizer) | Deterministic trigger, not a persona |
| Reflection | **Node on retry path only** | Only when Critic fails — loop guard: max 2 iterations |
| HITL | **Interrupt** (LangGraph interrupt / AG-UI needsApproval) | Only for tool authorization and final approval, never for trivia |

Two-agent ceiling for the core loop: **Planner → Researcher → Critic → Synthesize**, with Critic able to re-queue Researcher (bounded). Anything beyond that is a showcase feature, not the default path.

---

## 4. Advanced RAG — what's actually worth it

Current pipeline: `question → HyDE → hybrid (dense+FTS) → RRF → Cohere rerank → agent loop → answer`.

**Worth implementing (ordered by impact):**

1. **Metadata filtering + pre-filtering** — `chunk_metadata` JSONB (author/date/source) already stored; wire it into retrieval now (enables workspace/date/source filters).
2. **Parent-child retrieval** — retrieve child chunks but **return parent sections** as context; fixes fragment citations.
3. **Multi-query / query decomposition** — cheap-model node emitting 2–3 paraphrases/sub-questions, fused via existing RRF.
4. **Context selection + lost-in-the-middle mitigation** — deterministic: order chunks by rerank score with **recent-first for long context**.
5. **Context compression** — LLM-compress low-scoring chunks (or extractive: keep top-k sentences via rerank scores).
6. **Citation grounding enforcement** — require synthesized claims to map to chunk spans (spans already on `Citation`); count ungrounded sentences as a metric and fail the run above threshold.

**Sketch (do not do):** contextual retrieval (only if chunk scores plateau), RAG-fusion beyond multi-query, Property Graph RAG, auto-hierarchical chunking.

**Full pipeline for V3:**

```
Query → Query Analysis (rewrite/decompose, cheap model) → Metadata Pre-filter
      → Multi-query × retrieval (hybrid) → RRF fusion → Rerank
      → Parent-child expansion → Context selection/compression
      → Generate (grounded, spans) → Verify (faithfulness + citation) → Answer
```

---

## 5. Agent memory — where each kind lives

| Memory | Store | Notes |
|---|---|---|
| Working memory (current run) | **LangGraph state** | Already done — keep it out of DB |
| Conversation memory | **PostgreSQL** (`conversation_threads` + `research_runs`) | Add a rolling **summary** field updated by a post-run node |
| Episodic memory (past runs) | **PostgreSQL** (runs) + **Redis** TTL cache of recent summaries | "What did we do last session" |
| Semantic memory (facts across sessions) | **pgvector** `memory_entries` table | Only when V3 usage proves recall gaps |
| Session memory | **Redis** with TTL, written by summarizer node | Fast re-entry, cheap |

Rule: Postgres = durable truth; Redis = fast TTL'd layer; vector store = only for *searchable* memory, and only after conversation summary proves insufficient.

---

## 6. Tool ecosystem

Build a **tool gateway** (one `tools/` layer inside the backend, MCP-shaped interface):

| Tool | Priority | Risk controls |
|---|---|---|
| Web search (explicit API) | High | Rate limit, result validation (schema), domain allow/deny |
| URL/document fetch | High | **SSRF guard** (block private ranges), size cap, timeout, HTML→text sanitization |
| Internal KB (retrieval) | Already exists | Workspace-scoped |
| Repo/code search | Medium | Git clone timeout, size cap |
| SQL (read-only) | Low | Read-only role, LIMIT enforcement, schema allow-list |
| Calculator | High (cheap) | Deterministic `ast`-based evaluator, no `eval()` |

Cross-cutting: **tool registry with schemas** (Pydantic), per-tool **timeout + retry policy** (reuse `src/shared/retry.py`), **per-tool rate limits** (reuse Redis counter from `rate_limit.py`), **result size caps + content-type validation**, and **tool-level spans** (input hash, output size, latency, cost). Authorization: tool permission map per user/workspace, enforced in the gateway, not the agent.

---

## 7. Reliability engineering

- **Budgets (add now):** per-run iteration cap (have it — `MAX_ITERATIONS=5`), per-run token budget, per-run time budget (`asyncio.wait_for` around graph invoke), per-run cost ceiling.
- **Circuit breakers:** stateful breaker around the provider fallback chain (e.g., 5 failures/30s → skip provider); also for rerank/embed APIs.
- **Retries:** exponential backoff with jitter on embed/rerank/LLM calls; arq retry with `job_try` cap for ingestion jobs.
- **Hallucination defense:** insufficient-evidence refusal (hard-coded) + Critic verification node + citation-grounding metric (fail if ungrounded share > threshold).
- **Retrieval/tool failure:** degrade to refusal via existing `RetrievalError` mapping; never fabricate.
- **Infinite loops:** iteration cap (have), plus **self-loop detection** (same tool+args seen twice → break), plus tool result hash dedup.
- **Context overflow:** token budget on context assembly; overflow → auto-compact history.
- **Partial failures:** run state machine already marks `failed`; add **resume via checkpointer** (Postgres checkpointer exists — resume rather than redo).
- **Conflicting sources:** surface conflict explicitly ("Sources A and B disagree") via synthesis instruction + Critic check.

---

## 8. Evaluation system — build this first in V2

**Offline golden set:** 50–100 curated question/answer pairs with: workspace fixture, expected cited chunks, expected answer, confidence label. Store as JSON/YAML fixtures under `tests/fixtures/eval/`.

**Metrics (all computable on current data):**

- Retrieval: recall@k, precision@k, MRR, nDCG@k (ground truth = expected chunk IDs)
- Reranker effectiveness: **ΔNDCG before/after rerank** — the retrieval spec claims it but never verifies it; the single most credible engineering artifact
- Generation: answer correctness (LLM-as-judge + lexical), faithfulness (claim-level entailment), citation correctness (% cited spans matching cited chunks), citation completeness (% claims cited)
- Agent: tool-use accuracy, trajectory quality (step count, retry rate, dead-ends)
- Cost/latency: tokens per answer, $ per answer, p95 latency per stage

**Mechanism:** a `scripts/eval/run_eval.py` harness that runs the real pipeline headlessly, writes JSON results, and a CI step (`uv run pytest tests/eval/`) gating on regression thresholds (recall, faithfulness, citation completeness, latency). Offline — no live APIs.

---

## 9. Observability

**Trace: one `agentic.request` root span per question**, child spans: `auth → plan → query_analysis → retrieve.{each} → rerank → tool.{name} → llm.{provider,model} → verify → synthesize → respond`. Log: question hash, workspace, model used, tokens in/out, cost, latency per stage, cache hit/miss.

**Dashboards (logfire or Grafana):** cost per question/day, p95 latency by stage, cache hit-rate over time, hallucination-flag rate, tool failure rate, ingestion throughput/success, provider failure share, token budget exhaustion rate.

**Alert on:** cache hit-rate collapse, verify-fail rate > threshold, provider fallback share > 20%, ingestion failure rate, p95 > SLO.

---

## 10. Performance & cost — prioritized

| Technique | Impact | Effort | Status |
|---|---|---|---|
| Semantic cache (question-level) | ★★★★★ | M | **Complete (ADR-007)**: invalidation + metrics done; flag-off → enable when ready |
| Retrieval cache (query→chunks) | ★★★★ | S | Not present — TTL'd Redis cache on retrieval results |
| Embedding cache (text→vector) | ★★★★ | S | Not present — LRU in-process |
| Prompt/context caching | ★★★ | M | Only where provider supports cache keys |
| Model routing (small/large) | ★★★★ | M | Gateway exists (ADR-003) — route plan/verify/summarize to 8B, synthesize to flagship |
| Streaming | ★★ | S | SSE/AG-UI already streams — finish parity for WS |
| Async + parallel retrieval (multi-query) | ★★★ | M | `asyncio.gather` over decomposed queries |
| Batch embeddings | ★★ | S | `embed_texts` already batches (ingestion) |
| Context reduction | ★★★★ | M | Section 4 compression — cuts tokens per answer |
| Background ingestion | ★★★★ | Done | arq workers already |

---

## 11. Security

- **Prompt injection (direct):** system-prompt hardening + input guards (length, allowed content); never surface prompts (already a rule).
- **Indirect (documents/websites):** retrieved content marked as *data, not instructions* — delimiters + explicit instruction; strip `<system>`-style directives from extracted text. The #1 RAG vulnerability; zero defense today.
- **Tool abuse:** per-tool permission map, tool input schema validation, output caps, rate limits.
- **SSRF:** URL fetch tool must block loopback/private ranges (`ipaddress` checks + DNS rebinding mitigation), HTTPS-only.
- **Data/tenant isolation:** workspace scoping exists in queries — but it's security-by-query with stub auth. Real auth + FK enforcement + a "leak test" in the eval suite (cross-workspace question must return nothing).
- **Secrets:** API keys in env (`.env` gitignored), never committed to repos.
- **Malicious documents:** size caps (have), magic-byte validation (have for PDF), extraction-time sanitization, no macros/scripts (PDFs are text-extracted only — good).
- **Untrusted content in answers:** verification node treats retrieved content as untrusted input; citations must trace to workspace-owned chunks only.

---

## 12. Production architecture

```
Browser (Next.js) ──► API Gateway (FastAPI, authn/authz)
                         │
   ┌─────────────────────┼──────────────────────────┐
   ▼                     ▼                          ▼
Research service      Ingestion service          Voice service
   │                     │                          │
   ├─ LangGraph graph    ├─ arq worker ─► extract   │
   │  (plan/research/    │  ├─ chunk (Chonkie)      │
   │   critic/synth)     │  ├─ embed (Cohere)       │
   ├─ LLM Gateway (LiteLLM: Groq→OpenRouter→local)  │
   ├─ Tool Gateway (MCP: web, fetch, KB, calc)      │
   ├─ Semantic cache (Redis)                        │
   ├─ Eval harness (offline, CI)                    │
   └─ Observability (logfire + langfuse + dash)     │
                                                     ▼
PostgreSQL (pgvector, runs, threads, memory) ◄── Redis (cache, rate, queue)
Cloudflare R2 (raw uploads) ◄─────────────────── S3 client
```

Data flows: upload → storage+dedup → arq → extract → chunk → embed → chunks+pgvector → query → authz → cache check → plan → analyze → retrieve → rerank → verify → synthesize → respond (traced end-to-end).

---

## 13. Repository structure (target)

```
apps/api/src/
  auth/           # real auth (JWT, sessions) — replaces stub
  research/       # graph: plan, research, critic, synthesize (separate files per node)
  retrieval/      # pipeline: analyze, multi-query, hybrid, rerank, compress, verify
  tools/          # tool gateway: registry, permissions, web/fetch/calc/sql
  ingestion/      # (exists) + DLQ, retry policies
  memory/         # summarizer node, session memory, semantic memory writer
  eval/           # harness + fixtures + metrics (offline)
  observability/  # (exists) + dashboards config
  shared/         # gateway, redis, retry, budgets, circuit breaker
tests/
  eval/           # golden-set regression gates
scripts/eval/run_eval.py
```

Frontend stays feature-first (`features/research/...` already good); add `features/conversations/` state machine for HITL.

---

## 14. Differentiators (pick 5-7)

1. **Retrieval evaluation harness with ΔNDCG rerank verification** — "proves" the reranker instead of claiming it.
2. **Citation verifier + ungrounded-sentence metric** — grounded answers are *measured*, with CI gate.
3. **Deterministic planner + budget system** (token/time/cost ceilings with hard enforcement).
4. **Semantic cache with invalidation + hit-rate telemetry** — cost engineering depth.
5. **Prompt-injection defense for retrieved content** + cross-tenant leak tests in the eval suite.
6. **Tool gateway with per-tool authz, timeouts, and SSRF guard** — MCP done safely.
7. **Cost-per-question dashboard with model routing** — operational maturity signal.
8. **HITL interrupts (needsApproval) for tool authorization** — rare in portfolios, immediately credible.

---

## 15. Prioritized roadmap

**Must have (V2, weeks 1–6):** composed LangGraph nodes (plan/verify/synthesize); eval harness + golden set + CI gate; retrieval caching + embedding cache; context selection/compression; real auth (JWT+workspace); semantic cache enablement (invalidation + metrics already shipped); token/time/cost budgets.

**Should have (V3, weeks 7–10):** multi-query decomposition; parent-child retrieval; metadata pre-filtering; session summarization memory; tool gateway with web+fetch (with SSRF/rate limits); critic node on retry path; prompt-injection defenses + leak tests.

**Advanced (weeks 11–12+):** semantic/episodic memory; circuit breakers; cost dashboards + alerting; SQL tool; load testing; DLQ.

**Experimental (portfolio showcase, later):** multi-agent debate, graph RAG, autonomous long-horizon tasks, agent teams.

---

## Target architecture (one diagram)

```
Question
  │ authz ─► semantic cache ─(hit)─► cached answer
  ▼
[Plan]─(cheap LLM, schema-validated, fallback single-step)
  ▼
[Query Analysis] ─► [Multi-query] ─► [Hybrid Retrieve] ─► [RRF] ─► [Rerank]
  ▼
[Parent-child expand] ─► [Context select/compress] ─► [Budgets check]
  ▼
[Researcher agent loop] (tools via gateway: KB, web, fetch, calc)
  ▼
[Critic/Verify] ──(fail ≤2 retries)──► back to Researcher
  ▼
[Synthesize] ─► [Citation verify] ─► [Answer + spans]
  ▼
[Memory summarizer] → [Episodic]   [Cost/latency/trace → dashboards]
```

## 12-week plan

| Week | Track |
|---|---|
| 1–2 | Eval harness + golden set; **baseline metrics** (recall, faithfulness, ΔNDCG) |
| 3 | Refactor agent → composed graph (plan/research/synth nodes) |
| 4 | Budgets (token/time/cost) + retrieval caching + embedding cache |
| 5 | Context selection/compression + parent-child retrieval |
| 6 | Real auth (JWT + workspace) + leak tests; flip semantic cache on (invalidation + metrics shipped) |
| 7–8 | Multi-query + metadata filters; session memory summarizer |
| 9 | Tool gateway (web + fetch, SSRF, per-tool limits); HITL interrupt |
| 10 | Critic/verifier node + ungrounded-metric CI gate; prompt-injection defenses |
| 11 | Dashboards + alerting + cost-per-question; circuit breakers |
| 12 | Load test, DLQ, security review, portfolio write-up |
