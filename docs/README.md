# Agentic Research Workspace

## Purpose
A workspace where a user uploads documents (PDF, code repo, audio), asks a
question, and receives a grounded, citation-backed answer while watching
plain-language progress updates. This README orients any reader — human or
coding agent — to the docs set and where to start.

## Dependencies
- Source-of-truth architecture diagram: `docs/architecture.html` (frozen V1 design)
- This doc set scopes a smaller **MVP** out of that V1 design — see `PRD.md`

## Scope
This file: orientation only. No implementation detail lives here.

## Read This First If You Are a Coding Agent
Go to **`AGENTS.md`** now. It defines the required reading order and rules
before you write any code.

## Doc Map

| File | Answers |
|---|---|
| `PRD.md` | What are we building, and what is explicitly *not* MVP? |
| `AGENTS.md` | Rules for AI coding agents working in this repo |
| `conventions.md` | Folder structure, naming, approved libraries, patterns |
| `schema.md` | Core entities, relationships, ownership boundaries |
| `docs/adr/*` | Why LangGraph, Turbovec, and the Model Gateway pattern were chosen |
| `docs/specs/*` | Contract (inputs/outputs/tools/success criteria) for each MVP component |
| `docs/ui/ux.md` | What the user sees, and the rule against exposing reasoning |
| `docs/architecture.html` | Full V1 system diagram — interactive, click any node |

## What the MVP Does
1. User uploads a PDF, repo, or audio file.
2. User asks a question.
3. System returns an answer with citations back to source chunks.
4. User watches named progress stages (not raw reasoning) while it works.

## MVP Stack at a Glance

| Layer | Choice |
|---|---|
| Frontend | Next.js |
| API | FastAPI (REST + WebSocket) |
| Orchestration | LangGraph — single Research Agent node |
| Vector retrieval | Turbovec |
| Relational store / source of truth | PostgreSQL |
| Local model serving | LM Studio (OpenAI-compatible), Qwen3 4B or Gemma 3 4B |
| Embeddings | BGE-M3 (self-hosted) |
| Rerank | BGE-Reranker-v2-m3 (self-hosted) |
| Observability | Langfuse |

Full rationale for each choice lives in `docs/adr/`. Anything not in this
table (Critic, memory layers, RBAC roles) is **Phase 2** - see
`PRD.md` -> Non-Goals. Shipped since the MVP freeze: the semantic answer
cache (ADR-007, default on), JWT auth (ADR-008, `AUTH_MODE=jwt`),
the composed research pipeline (`docs/specs/research-pipeline.md`), and
the offline eval harness (`docs/specs/evaluation.md`).

## Repository Structure
```
apps/
├── web/        Next.js frontend
├── api/        FastAPI gateway
└── worker/     Async ingestion + job processing

src/
├── research/       Research Agent (LangGraph)
├── retrieval/       Hybrid search + rerank
├── ingestion/       Upload → chunk → embed pipeline
├── auth/             (stubbed for MVP — see PRD Non-Goals)
├── observability/   Langfuse tracing
└── shared/

docs/
infra/
tests/
```
Feature-first, not technology-first. See `conventions.md` for the full rule.
