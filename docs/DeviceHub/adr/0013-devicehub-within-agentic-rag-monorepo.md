# ADR-0013: Host DeviceHub inside the existing Agentic RAG monorepo

Status: Accepted · Date: 2026-11-16

## Context

ADR-0001 decides on a modular monorepo with few deployable units. ADR-0002 splits the device plane (Rust) from the agent plane (Python). The supporting documents were written assuming a standalone `devicehub/` repository with `crates/`, `agent/`, `web/`, `firmware/`, `deploy/`, and `migrations/` at the root.

The actual host repository is `enterprise-agentic-knowledgebase`: a pnpm + Turborepo monorepo containing a working Agentic Knowledge Base (`apps/api` FastAPI + LangGraph, `apps/web` Next.js, `apps/docs`, shared `packages/*`, PostgreSQL + pgvector, Redis, Alembic migrations, Render deployment, and CI).

Two constraints rule out a naive merge:

1. The existing Knowledge Base must remain a separately demonstrable portfolio product, with its chat UI, streaming, citations, ingestion, retrieval, reranking, agent workflow, and deployment intact.
2. DeviceHub is an *additive extension* that reuses those reasoning capabilities. A second repository would duplicate the RAG corpus, the model gateway, and the evaluation harness — the exact thing the extension exists to demonstrate.

## Decision

Host DeviceHub in this repository, additively:

- **No second repository and no second copy of the app.** Logical boundaries from ADR-0001/0002 are preserved; only physical paths change.
- **Rust device plane** goes to a new root `crates/` workspace plus `apps/hub-api`, `apps/hub-worker`, `apps/simulator`, `apps/bridge`.
- **Python agent plane reuses `apps/api`.** The DeviceHub investigation graph lives in `apps/api/src/devicehub/` and calls the Rust API for device evidence. No second Python service is created without a measured reason.
- **Web reuses `apps/web`.** DeviceHub routes are added under `apps/web/app/`; existing routes are not replaced.
- **PostgreSQL is reused** from the existing instance. DeviceHub schemas (`core`, `agent`, `docs`) are additive and are written by an independent migration path. Existing `public` tables and Alembic revisions are never rewritten.
- **Documentation stays in `docs/DeviceHub/`.** The standalone layout in `SERVICE_BOUNDARIES` §6 is replaced by the mapping in `REPOSITORY_INTEGRATION.md`.
- **Build order is unchanged.** S0–S5 and the Phase 1–10 plan still apply.

## Alternatives considered

- **Standalone DeviceHub repository.** Clean isolation and an independent deploy, but duplicates ingestion, retrieval, embeddings, the model gateway, and evals; splits the demo into two products; and contradicts the stated goal of reusing RAG.
- **Restructure the host repository into DeviceHub's layout.** Superficially tidy, but it moves and rewrites working Knowledge Base code and deployment config — prohibited by the preservation rules and high-risk for no product benefit.
- **A separate Python `agent-service` app inside the monorepo.** Keeps ADR-0002's service split literal, but introduces a second FastAPI app, a second settings module, a second test suite, and a second deploy target before any measured need. The HTTP boundary is still enforced by having Python call `hub-api` rather than the database.
- **A second Next.js app for the dashboard.** Guarantees UI duplication and a second build; extending `apps/web` keeps one frontend.

## Consequences

Positive:

- One install, one lockfile, one CI pipeline, one demo surface.
- DeviceHub reuses the existing RAG pipeline, model gateway, and evaluation harness instead of forking them.
- The Knowledge Base remains runnable and demonstrable on its own.

Negative:

- The Python app now hosts two domains (`research` and `devicehub`), so feature-folder discipline matters more.
- Rust toolchain requirements enter a repository whose CI is currently Python + TypeScript only.
- Two migration paths exist; the boundary between `public` and the new schemas must be enforced by review.

Risks and mitigations:

| Risk | Mitigation |
|---|---|
| DeviceHub changes leak into existing RAG behavior | Phase gates, additive-only changes, existing test suite run each phase |
| Schema ownership blurs | `public` = existing KB (Alembic), `core` = Rust, `agent`/`docs` = Python; documented in `REPOSITORY_INTEGRATION.md` §4 |
| Port collisions (3001 is the docs site) | Port table in `REPOSITORY_INTEGRATION.md` §5; Grafana moves |
| Python `apps/api` becomes a dumping ground | Feature-first modules; no new top-level `agents/`, `services/`, or `utils/` |

## Revisit when

The Python agent plane needs independent scaling, independent deployment, or a different runtime from the Knowledge Base API; or the DeviceHub dashboard requires a separate frontend deploy; or CI duration becomes dominated by unrelated domains.
