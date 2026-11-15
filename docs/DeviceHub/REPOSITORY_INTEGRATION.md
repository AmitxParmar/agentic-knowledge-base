# REPOSITORY INTEGRATION

How DeviceHub's logical layout maps onto the **existing** `enterprise-agentic-knowledgebase` monorepo. This document exists because most DeviceHub design documents were written assuming a standalone `devicehub/` repository.

Decision record: [ADR-0013](adr/0013-devicehub-within-agentic-rag-monorepo.md). Logical boundaries in [SERVICE_BOUNDARIES](SERVICE_BOUNDARIES.md) are unchanged; only physical paths are adapted.

## 1. Verified baseline (exists today)

| Concern | Reality in this repository |
|---|---|
| Workspace | pnpm 9 + Turborepo; `apps/*`, `packages/*` |
| Web | `apps/web` — Next.js 16, React 19, port 3000 |
| Docs site | `apps/docs` — Next.js 16, **port 3001** |
| Python app | `apps/api` — FastAPI + LangGraph + arq, port 8000 |
| Python layout | `apps/api/src/{research,retrieval,ingestion,auth,observability,shared,eval}` |
| Migrations | `apps/api/alembic/versions/` — 9 revisions, default `public` schema |
| Database | PostgreSQL + pgvector; tables `documents`, `chunks`, `citations`, `research_runs`, `conversation_threads`, `ingestion_jobs`, `users`, `workspaces` |
| Checkpoints | `public.langgraph_checkpoints`, `public.langgraph_checkpoint_writes` (custom asyncpg checkpointer) |
| Cache / queue | Redis (Upstash) via `REDIS_URL`; arq worker |
| Object storage | Cloudflare R2 / S3-compatible (`R2_*`) |
| Deploy | `apps/api/Dockerfile` (API + worker + migrations in one container) + `apps/api/render.yaml`; frontend deployed separately |
| CI | `.github/workflows/ci.yml` — Python 3.13 ruff/pyright/pytest, turbo lint/types, non-blocking eval |
| Compose | **None.** No `docker-compose.yml`, no local Postgres/Redis. |
| Rust | **None.** No `Cargo.toml`, no workspace. |
| Firmware | **None.** No `firmware/`, no sketches. |

## 2. Logical component → monorepo path

Paths are **planned**. Nothing in this table is implemented in Phase 1.

| DeviceHub component | Language | Planned location | Precedent in this repo |
|---|---|---|---|
| `hub-api` | Rust (Axum, Tokio) | `apps/hub-api/` | `apps/api` (independent app in the same workspace) |
| `hub-worker` | Rust (Tokio) | `apps/hub-worker/` | arq worker currently lives inside `apps/api` |
| shared Rust crates | Rust | `crates/{common,domain,db,mqtt,policy}` | none yet — new workspace root |
| `agent-service` | Python (FastAPI, LangGraph) | reuse `apps/api`; DeviceHub graph in `apps/api/src/devicehub/` | `apps/api/src/research/` |
| `web` dashboard | TypeScript | extend `apps/web` (new routes under `app/`) | `app/research`, `app/library`, `app/runs`, `app/usage` |
| `simulator` | Rust | `apps/simulator/` | none |
| `bridge` | Rust (or Python) | `apps/bridge/` | none |
| `firmware` | C++ (Arduino) | `firmware/` | none |
| infra / compose | YAML | `deploy/` | `apps/api/render.yaml` only |
| core migrations | SQL | `apps/hub-api/migrations/` (SQLx) | `apps/api/alembic/versions/` |
| docs | Markdown | `docs/DeviceHub/` | `docs/` |

Documentation that still shows `devicehub/crates/...` is describing the **original standalone assumption**, not this repository.

## 3. What this changes, and what it does not

| Boundary | Preserved? |
|---|---|
| Rust owns device truth, safety, commands, policy | Yes — no Rust code exists yet; the boundary is unchanged |
| Python owns reasoning and RAG, accesses device data only via the Rust API | Yes |
| Next.js owns presentation only | Yes |
| The existing Knowledge Base stays a standalone demoable product | Yes — DeviceHub adds routes; it does not rewrite existing ones |
| One repository, few deployable units (ADR-0001) | Yes — same rule, more units |

## 4. Database and schema strategy

The existing application uses the default `public` schema and a single Alembic environment. DeviceHub's data model assumes `core`, `agent`, and `docs` schemas with separate owners.

| Schema | Owner | Status | Migration tool |
|---|---|---|---|
| `public` (existing KB) | Python | **Exists** — must not be rewritten | Alembic, `apps/api/alembic` |
| `core`, `agent`, `docs` | Rust / Python | Planned | Separate migration path; needs `include_schemas` or a second environment |

Rules for Phase 2 onward:

1. New DeviceHub schemas are created by additive migrations only. Existing tables and revisions are never altered or renamed.
2. The existing Alembic chain stays the only writer of `public`. A second, independent migration path owns `core`/`agent`/`docs`.
3. Reuse the existing PostgreSQL instance (currently Neon via `DATABASE_URL`), not a second database, unless isolation proves necessary.

### Open questions raised by the existing implementation

| # | Finding | Impact |
|---|---|---|
| I1 | `SERVICE_BOUNDARIES` §4 assigns `docs.*` (documents, chunks, embeddings) to Python, but this repo already owns `public.documents` and `public.chunks` with pgvector. | Creating `docs.*` would fork the RAG corpus. Reusing the existing tables with a DeviceHub namespace is likely correct; decide before Phase 7. |
| I2 | `DATA_MODEL` §4 declares `embedding vector(1536)`; the existing corpus uses Cohere `embed-v3` at **1024** dimensions (`EMBEDDING_DIM`). | Any DeviceHub manual embedding must use 1024 to share the same column, or live in a separate table. |
| I3 | `DATA_MODEL` §3 describes LangGraph checkpoints as `agent.*`; the existing implementation uses `public.langgraph_checkpoints`. | The investigation graph can reuse the existing checkpointer, or add a namespace; do not duplicate blindly. |

These are **Phase 2 decisions**, recorded here so they are not discovered late.

## 5. Ports

| Port | Current owner | DeviceHub plan | Conflict |
|---|---|---|---|
| 3000 | `apps/web` | same app, new routes | none |
| 3001 | `apps/docs` | ~~Grafana~~ | **Grafana must move** (e.g. 3003) |
| 8000 | `apps/api` | reuse for `agent-service` | none |
| 8080 | — | `hub-api` | none |
| 8090 | — | not needed if Python stays in `apps/api` | none |
| 1883/8883 | — | Mosquitto (planned) | none |
| 5432 | — | reuse existing Postgres | none |
| 8123/9000 | — | ClickHouse — **not in Phase 1** | none |
| 9090 | — | Prometheus (planned, S5) | none |
| 9101 | — | `hub-worker` metrics (planned) | none |

`LOCAL_DEVELOPMENT.md` has been updated to reflect this table.

## 6. Environment variables

Existing names must not be renamed or repurposed. DeviceHub variables are additive and domain-prefixed.

| Existing (do not change) | DeviceHub (planned) |
|---|---|
| `DATABASE_URL`, `REDIS_URL` | `DATABASE_MIGRATOR_URL` (owner role for `core` migrations) |
| `MODEL_GATEWAY_*`, `COHERE_*` | `MQTT_URL`, `MQTT_SERVICE_USER`, `MQTT_SERVICE_PASSWORD` |
| `R2_*`, `LOGFIRE_TOKEN`, `LANGFUSE_*` | `JWT_SIGNING_KEY`, `SERVICE_HMAC_SECRET`, `DEVICE_COMMAND_KEY_SEED` |
| `APP_ENV`, `APP_DEBUG`, `CORS_ORIGINS`, `UPLOAD_DIR` | `HUB_API_URL`, `AGENT_SERVICE_URL`, `HEARTBEAT_TIMEOUT_SECS`, `INGEST_*` |

Notes:

- `HUB_API_URL` and `AGENT_SERVICE_URL` must not collide with the existing `NEXT_PUBLIC_*` or model-gateway variables.
- The existing repository has **no `.env.example`**, although `apps/api/SETUP.md` and `LOCAL_DEVELOPMENT.md` both reference one. Creating one is a host-project documentation fix, tracked in the [Phase 1 report](PHASE_1_REPORT.md#6-host-project-gaps-recorded-not-fixed), not a DeviceHub change.
- No secret is committed. `apps/api/.env` is untracked and git-ignored (verified).

## 7. Directory rules for Phase 2 onward

- New Rust code lives under a root `crates/` workspace plus `apps/hub-api`, `apps/hub-worker`, `apps/simulator`, `apps/bridge`. It does not go inside `apps/api`.
- DeviceHub Python code lives inside `apps/api/src/devicehub/` (feature-first), not in a new top-level `agent/` directory.
- DeviceHub web routes live under `apps/web/app/`, reusing `features/` conventions.
- No top-level `services/`, `utils/`, `agents/`, or `prompts/` directory — consistent with `docs/conventions.md`.
