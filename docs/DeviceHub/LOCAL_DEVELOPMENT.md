# LOCAL_DEVELOPMENT

Docker Compose, environment variables, migrations and run commands.

> **Status:** this document mixes two things and labels them explicitly. **Current** rows describe the repository as it exists today (verified 2026-11-16). **Planned** rows describe the target experience and are not implemented. Command names such as `just …` are conventions to implement in Phase 2+, not existing commands. Anything hardware-specific is `[HW-TBD]`. See [REPOSITORY_INTEGRATION](REPOSITORY_INTEGRATION.md) for the path, port, and environment mapping.

## 1. Prerequisites

| Tool | Purpose | Status in this environment (2026-11-16) |
|---|---|---|
| Docker + Docker Compose v2 | Infra and services | ✅ Docker 29.7.2, Compose v5.5.1 |
| Rust (stable, via `rustup`) | `hub-api`, `hub-worker`, simulator, bridge | ✅ cargo/rustc 1.98.0, rustup 1.29.0 — **no Rust code exists yet** |
| `just` | Task runner | ❌ not installed; no `justfile` in the repo |
| `sqlx-cli` | PostgreSQL migrations | ❌ not installed |
| Python 3.11+ and `uv` | existing `apps/api`; DeviceHub graph | ✅ uv 0.13.1; `apps/api/.venv` runs Python 3.13 |
| Node 20+ and `pnpm` | `apps/web`, `apps/docs` | ✅ Node 26.7.0, pnpm 9.0.0 |
| PostgreSQL | existing Knowledge Base storage | ⚠️ no local instance; `DATABASE_URL` points at a managed Postgres (Neon) |
| Redis | arq queue and caches | ⚠️ no local instance; `REDIS_URL` points at a managed instance (Upstash) |
| Arduino CLI or IDE `[HW-TBD]` | Flash firmware | ⚠️ `arduino-cli` present; board unknown, nothing flashed |
| `mosquitto_pub` / `mosquitto_sub` (optional) | Manual MQTT checks | ❌ not installed |
| `k6` (optional) | Load tests | ❌ not installed |

No listener was found on 5432, 6379, or 1883 at inspection time.

## 2. Compose services

**Planned — no Compose file exists in this repository.** The only container today is `apps/api/Dockerfile`, which runs the FastAPI gateway, the arq worker, and Alembic migrations in one container against managed Postgres and Redis. Profiles below are the intended S1+ shape.

Profiles keep the default start light.

| Service | Image/source | Port(s) | Profile | Status |
|---|---|---|---|---|
| `mosquitto` | eclipse-mosquitto | 1883 (localhost), 8883 (TLS) | default | planned |
| `postgres` | postgres + pgvector | 5432 | default | reuse existing managed Postgres; local container optional |
| `clickhouse` | clickhouse-server | 8123 (HTTP), 9000 | `analytics` | **not before S2** (ADR-0004) |
| `hub-api` | `apps/hub-api` | 8080 | default | planned |
| `hub-worker` | `apps/hub-worker` | 9101 (metrics) | default | planned |
| `agent-service` | existing `apps/api` | 8000 | `ai` | reuse existing app |
| `web` | existing `apps/web` | 3000 | default | exists |
| `otel-collector` | otel-collector | 4317 | `obs` | planned (S5) |
| `prometheus` | prometheus | 9090 | `obs` | planned (S5) |
| `grafana` | grafana | **3003** | `obs` | planned (S5) — 3001 is the existing docs site |
| `langfuse` (+ its deps) | langfuse | 3002 | `obs` | optional; Langfuse keys already exist |

Typical combinations:

```bash
just up               # default: broker, postgres, api, worker, web   (vertical slice S1)
just up analytics     # + ClickHouse
just up ai            # + agent-service
just up obs           # + OTel, Prometheus, Grafana, Langfuse
just up all           # everything
just down             # stop, keep volumes
just nuke             # stop and delete volumes
```

For fast Rust iteration, run `hub-api` and `hub-worker` on the host with `cargo watch` and keep only infra in Docker: `just infra`.

## 3. Environment variables

Copy `.env.example` to `.env` (git-ignored). Names only are committed.

> **Current gap:** this repository has **no `.env.example`**, although both this document and `apps/api/SETUP.md` reference one. The working file is `apps/api/.env` (untracked, ignored). Creating a committed `.env.example` is a host-project fix, tracked in [PHASE_1_REPORT](PHASE_1_REPORT.md).

| Variable | Example (dev) | Used by | Notes |
|---|---|---|---|
| `DATABASE_URL` | `postgres://hub:hub@localhost:5432/devicehub` | api, worker | App role (RLS enforced) |
| `DATABASE_MIGRATOR_URL` | `postgres://hub_admin:…@localhost:5432/devicehub` | migrations | Owner role |
| `CLICKHOUSE_URL` | `http://localhost:8123` | api, worker | |
| `CLICKHOUSE_USER` / `CLICKHOUSE_PASSWORD` | `hub` / `…` | api, worker | |
| `MQTT_URL` | `mqtt://localhost:1883` | worker, api | Use `mqtts://…:8883` with TLS |
| `MQTT_SERVICE_USER` / `MQTT_SERVICE_PASSWORD` | `svc_worker` / `…` | worker, api | Service ACL |
| `JWT_SIGNING_KEY` | random 32+ bytes | api | Rotate via `kid` |
| `SERVICE_HMAC_SECRET` | random | api, agent | Signs internal calls |
| `DEVICE_COMMAND_KEY_SEED` | random | api | Derives per-device command keys |
| `HUB_API_URL` | `http://localhost:8080` | agent, web | |
| `AGENT_SERVICE_URL` | `http://localhost:8090` | api | |
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` | — | agent | Never logged |
| `EMBEDDING_MODEL` | — | agent | Must match `docs.chunk.embedding_model` |
| `LANGFUSE_HOST` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | — | agent | Optional |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | all | Optional |
| `RUST_LOG` | `info,hub=debug` | rust | |
| `HEARTBEAT_TIMEOUT_SECS` | `15` | worker | |
| `INGEST_BATCH_SIZE` / `INGEST_FLUSH_MS` | `1000` / `200` | worker | Benchmarked knobs |
| `INGEST_QUEUE_CAPACITY` | `10000` | worker | Backpressure bound |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8080` | web | |

Rules: no real secrets in git; dev-only defaults live in `.env.example`; production values come from a secret store.

## 4. First-time setup

### Current — Agentic Knowledge Base (verified)

```bash
pnpm install                                   # JS workspace
cd apps/api
uv sync                                        # creates/uses apps/api/.venv
uv run alembic upgrade head                    # existing migrations (public schema)
uv run python scripts/seed.py                  # optional demo data
uv run uvicorn app.main:app --reload --port 8000
uv run arq app.workers.WorkerSettings          # second terminal
pnpm --filter web dev                          # from repo root, port 3000
```

`DATABASE_URL` and `REDIS_URL` point at managed services; no local Postgres, Redis, or Compose stack is required today.

### Planned — DeviceHub (not implemented)

```bash
cp .env.example .env              # file does not exist yet
just infra                        # postgres, mosquitto (no clickhouse in S1)
just migrate                      # core migrations only in S1
just seed                         # demo tenant, admin user, sample devices
just up                           # hub-api, hub-worker, existing web
```

The dashboard is the existing web app at http://localhost:3000; DeviceHub routes are added later. `just` commands are conventions to implement, not current commands.

## 5. Migrations

| Store | Tool | Location | Command | Status |
|---|---|---|---|---|
| PostgreSQL `public` (existing KB) | Alembic | `apps/api/alembic/versions/` | `uv run alembic upgrade head` | exists — do not rewrite |
| PostgreSQL `core` | SQLx | `apps/hub-api/migrations/` | `just migrate-core` | planned |
| PostgreSQL `agent`, `docs` | Python-side migrations | `apps/api/` (separate environment) | `just migrate-agent` | planned |
| ClickHouse | ordered `.sql` + small runner | `migrations/clickhouse/` | `just migrate-ch` | **not before S2** |

The existing `public` schema and Alembic chain must not be altered to accommodate DeviceHub; see [REPOSITORY_INTEGRATION](REPOSITORY_INTEGRATION.md) §4.

```bash
just migrate               # core only in S1; agent/docs later; clickhouse not before S2
just migrate-new core add_incident_table   # create a new numbered migration
just migrate-check         # CI: fresh DB migrates, offline SQLx metadata up to date
just migrate-reset         # dev only: DeviceHub dev database ONLY — never the KB database
```

`migrate-reset` must never point at `DATABASE_URL`. The existing Knowledge Base database is not a scratch database.

Rules: forward-only migrations; each is reviewed with `EXPLAIN` where it adds indexes; RLS policies are created in the same migration as the table; CI applies all migrations to an empty database.

## 6. Running things

The `just …` commands below are **planned** (no justfile exists). Use the current commands in §4 for the Knowledge Base.

### Backend (host)
```bash
just api          # cargo run -p hub-api
just worker       # cargo run -p hub-worker
just test         # cargo test --workspace (+ integration tests with testcontainers)
just lint         # cargo fmt --check, clippy -D warnings
```

### Agent
```bash
just agent        # uv run uvicorn agent.main:app --reload --port 8090
just agent-test
just agent-ingest docs/manuals/        # chunk + embed device docs into pgvector
just agent-eval                         # run the evaluation scenarios, report to Langfuse
```

### Web
```bash
just web          # pnpm dev (port 3000)
just web-test
```

### Simulated fleet
```bash
just sim --devices 100 --rate 10hz --tenants 2                    # steady load
just sim --devices 1000 --rate 5hz --faults dup=0.01,late=0.02,malformed=0.005 --seed 42
just sim --scenario scenarios/reconnect-storm.yaml
```
Seeded runs are reproducible. The simulator registers its own devices through the API and uses real credentials.

### Physical robot `[HW-TBD]`
```bash
just firmware-build            # arduino-cli compile (board FQBN set in firmware/board.env)
just firmware-flash PORT=/dev/ttyUSB0
just bridge --serial /dev/ttyUSB0 --baud 115200 --device-id <uuid> --mqtt-url mqtt://localhost:1883
```
Bench protocol first: wheels lifted or motors disconnected, motor power switch off, kill switch reachable. Verify obstacle stop, `stop`, and comms-loss stop before any floor test.

### Manual MQTT checks
```bash
mosquitto_sub -h localhost -u svc_worker -P "$MQTT_SERVICE_PASSWORD" -t 'dh/v1/d/+/telemetry' -v
mosquitto_pub -h localhost -u d_<device_id> -P <secret> \
  -t dh/v1/d/<device_id>/telemetry -f samples/telemetry-v1.json
```

### Load and benchmarks
```bash
just bench-ingest --duration 5m --rate 5000 --out benchmarks/results/
just bench-queries
```
Each run writes a JSON file recording hardware, OS, dataset size, event rate, config knobs, and p50/p95/p99, CPU, memory. Results without conditions are not published.

## 7. Ports at a glance

`3000` web (exists) · `3001` docs site (exists) · `3002` Langfuse · `3003` Grafana · `4317` OTLP · `5432` Postgres · `8000` existing API / agent plane · `8080` hub-api · `8123` ClickHouse · `1883/8883` MQTT · `9090` Prometheus · `9101` worker metrics

## 8. Troubleshooting

| Symptom | Check |
|---|---|
| Device cannot connect | Credential synced to broker? `just broker-sync`; check broker logs for auth failure |
| No telemetry in dashboard | `mosquitto_sub` sees messages? Worker `dead_letter_total` rising? Identity mismatch? |
| Telemetry in Postgres but not ClickHouse | Profile `analytics` running? Worker sink retries metric |
| Agent never starts | `just up ai`; `AGENT_SERVICE_URL`; HMAC secret matches both sides |
| `sqlx` offline errors | `just sqlx-prepare` and commit `.sqlx/` |
| Serial port busy | Close the Arduino IDE serial monitor; only the bridge owns the port |
| Robot runs after disconnect | Stop: this is a firmware bug. Power off and verify the comms-loss stop on the bench |

## 9. CI

CI runs: format, clippy, Rust tests with ephemeral services, migration check on an empty DB, Python lint/tests/evals (smoke subset), web lint/typecheck/tests, container builds, dependency scans, and a short Compose integration test (simulator → ingest → API). The full benchmark and full eval suite run on demand or nightly.
