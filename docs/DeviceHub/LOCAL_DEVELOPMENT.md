# LOCAL_DEVELOPMENT

Docker Compose, environment variables, migrations and run commands.

> **Status:** this is the target developer experience, written before the repository exists. Command names (`just …`) and ports are conventions to implement in Phase 1; adjust this file as reality settles. Anything hardware-specific is `[HW-TBD]`.

## 1. Prerequisites

| Tool | Purpose |
|---|---|
| Docker + Docker Compose v2 | Infra and services |
| Rust (stable, via `rustup`) | `hub-api`, `hub-worker`, simulator, bridge |
| `just` | Task runner |
| `sqlx-cli` | PostgreSQL migrations |
| Python 3.12+ and `uv` | `agent-service` |
| Node 20+ and `pnpm` | `web` |
| Arduino CLI or IDE `[HW-TBD]` | Flash firmware |
| `mosquitto_pub` / `mosquitto_sub` (optional) | Manual MQTT checks |
| `k6` (optional) | Load tests |

## 2. Compose services

Profiles keep the default start light.

| Service | Image/source | Port(s) | Profile |
|---|---|---|---|
| `mosquitto` | eclipse-mosquitto | 1883 (localhost), 8883 (TLS) | default |
| `postgres` | postgres + pgvector | 5432 | default |
| `clickhouse` | clickhouse-server | 8123 (HTTP), 9000 | `analytics` |
| `hub-api` | `crates/api` | 8080 | default |
| `hub-worker` | `crates/worker` | 9101 (metrics) | default |
| `agent-service` | `agent/` | 8090 | `ai` |
| `web` | `web/` | 3000 | default |
| `otel-collector` | otel-collector | 4317 | `obs` |
| `prometheus` | prometheus | 9090 | `obs` |
| `grafana` | grafana | 3001 | `obs` |
| `langfuse` (+ its deps) | langfuse | 3002 | `obs` |

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

```bash
git clone <repo> devicehub && cd devicehub
cp .env.example .env              # then fill in secrets (just gen-secrets can generate them)
just infra                        # start postgres, mosquitto (+ clickhouse if needed)
just migrate                      # apply all migrations (see §5)
just seed                         # demo tenant, admin user, sample devices
just up                           # start app services
```

Open the dashboard at http://localhost:3000. Seeded admin credentials are printed by `just seed` (dev only).

## 5. Migrations

| Store | Tool | Location | Command |
|---|---|---|---|
| PostgreSQL `core` | SQLx | `migrations/core/` | `just migrate-core` |
| PostgreSQL `agent`, `docs` | Python-side migrations | `agent/migrations/` | `just migrate-agent` |
| ClickHouse | Ordered `.sql` applied by a small runner (`just migrate-ch`) with a `schema_migrations` table | `migrations/clickhouse/` | |

```bash
just migrate               # core + agent + clickhouse in order
just migrate-new core add_incident_table   # create a new numbered migration
just migrate-check         # CI: fresh DB migrates, offline SQLx metadata up to date
just migrate-reset         # dev only: drop and recreate
```

Rules: forward-only migrations; each is reviewed with `EXPLAIN` where it adds indexes; RLS policies are created in the same migration as the table; CI applies all migrations to an empty database.

## 6. Running things

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

`3000` web · `3001` Grafana · `3002` Langfuse · `4317` OTLP · `5432` Postgres · `8080` hub-api · `8090` agent · `8123` ClickHouse · `1883/8883` MQTT · `9090` Prometheus · `9101` worker metrics

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
