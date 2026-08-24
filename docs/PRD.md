# PRD: Agentic Research Workspace — MVP

## Purpose
Define what the first shippable release of the Agentic Research Workspace
must do, and draw a hard line around what it must not attempt yet.

## Dependencies
- `docs/architecture.html` — full V1 architecture (source of truth for any
  detail not overridden below)
- This PRD scopes the **first build phase** out of that V1 design

## Scope
Product requirements only. No API contracts, schemas, or code — see
`docs/specs/` and `schema.md` for those.

## Background
The V1 architecture (frozen) describes a three-agent system — Planner,
Researcher, Critic — with semantic caching, plan reuse, long-term memory, and
nightly evaluation. Building all of it before validating the core loop is
over-engineering. The MVP builds the smallest slice that proves the core
value: **ask a question about your own documents, get a grounded answer.**

## Goals (MVP)
A user can:
1. Upload a document — PDF, code repository, or audio file.
2. Ask a question about what they uploaded.
3. Receive an answer with citations back to the specific source chunks.
4. Watch named progress stages while the system works.

The MVP is successful if all four hold up reliably under normal use.

## Functional Requirements

| ID | Requirement |
|---|---|
| F1 | Accept PDF, repo (zip or git URL), and audio file uploads |
| F2 | Extract content per source type, preserving structure where it matters (headings/tables for PDF, function/class boundaries for code) |
| F3 | Chunk content semantically, not by fixed token count |
| F4 | Embed chunks locally and index for both vector and keyword search |
| F5 | Accept a natural-language question scoped to an uploaded document set |
| F6 | Run a single Research Agent that retrieves evidence and drafts an answer |
| F7 | Every claim in the answer must be traceable to a retrieved chunk |
| F8 | Stream named progress events to the client during both ingestion and a research run |
| F9 | Persist documents, chunks, and run history in PostgreSQL |

## Non-Functional Requirements

| ID | Requirement |
|---|---|
| N1 | All model inference (chat + embedding + rerank) runs locally — no required external API |
| N2 | The model-serving layer is swappable without touching agent code (Model Gateway abstraction — see ADR-003) |
| N3 | Every agent run is traced in Langfuse |
| N4 | Ingestion runs asynchronously; upload requests return immediately |

## Non-Goals (Explicitly Deferred to Phase 2)

| Deferred | Why |
|---|---|
| Planner Agent | ~~Single-question MVP doesn't need multi-hop task decomposition yet~~ — **partially implemented** as a LangGraph *node* (not an agent): `docs/specs/research-pipeline.md`; eval harness provides the measurement baseline |
| Critic Agent / reflection loop | Add once we can measure how often the Researcher actually needs it |
| Plan Cache | Has nothing to reuse until plans repeat across runs |
| Semantic Cache (Redis) | ~~Optimization; premature before usage volume exists~~ — **implemented** as ADR-007, feature-flagged off by default |
| Working Memory / Semantic Memory / Conversation Summaries | Multi-session memory isn't required for a single ask-and-answer loop |
| MCP Tool Layer (web search, GitHub, filesystem tools) | Research Agent's MVP tool is retrieval-over-uploads only |
| RBAC / Scoped Retrieval / Secret Management / Tool Guardrails | Single-tenant MVP; full security zone waits for multi-tenant need |
| Input/Output Guardrails (LLM Guard, Guardrails AI) | Add once real misuse patterns are observed |
| RAGAS + DeepEval nightly eval | Needs a golden dataset and a live system to evaluate first |
| Prometheus + Grafana dashboards | Langfuse tracing is sufficient signal at MVP scale |
| Multi-provider Model Gateway (LiteLLM, OpenRouter, hosted fallback) | MVP gateway has one local backend; see ADR-003 |

Each of these exists in the V1 architecture and may be built later. Building
any of them now without a justifying metric is a process violation, not a
shortcut — see `conventions.md`.

## Assumptions
- Single-tenant use (one user/workspace) is acceptable for MVP; the schema
  still models `users`/`workspaces` so multi-tenant isn't a rewrite later.
- "Local model" means a 3B–4B instruction model (Qwen3 4B, Gemma 3 4B, or
  similar) served via LM Studio's OpenAI-compatible endpoint.

## Success Criteria
MVP ships when a user can upload → ask → receive a cited answer → watch
progress, end to end, without manual intervention.
