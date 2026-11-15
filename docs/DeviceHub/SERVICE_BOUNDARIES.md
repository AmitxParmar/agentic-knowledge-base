# SERVICE_BOUNDARIES

Who owns what. The rule of thumb: **Rust owns truth and safety, Python owns reasoning, Next.js owns presentation.**

## 1. Deployable units

Start as a modular monorepo ([ADR-0001](docs/adr/0001-modular-monorepo.md)). Logical components are many; deployable units are few.

| Unit | Language | Contains (logical components) |
|---|---|---|
| `hub-api` | Rust (Axum, Tokio) | Device API, auth, command service + policy gate, config service, query API, realtime gateway (SSE), internal agent-event endpoint |
| `hub-worker` | Rust (Tokio) | MQTT ingest worker, rules/incident engine, outbox dispatcher, presence tracker, broker credential sync |
| `agent-service` | Python (FastAPI, LangGraph) | Investigation graph, tool layer, RAG ingestion and retrieval, evals harness |
| `web` | TypeScript (Next.js) | Dashboard UI |
| `bridge` | Rust (or Python) on a host | Serial ⇄ MQTT bridge for the physical robot |
| `firmware` | C++ (Arduino) | Deterministic robot control and safety |
| `simulator` | Rust | Virtual device fleet, fault injection |
| Infra | — | Mosquitto, PostgreSQL (+pgvector), ClickHouse, OTel Collector, Prometheus, Grafana, Langfuse |

Split `hub-worker` further only for a measured reason (e.g. ingest needs independent scaling).

## 2. Responsibilities

### 2.1 Rust (`hub-api`, `hub-worker`)
Owns:
- All device, tenant, user, credential, command, config, incident, audit data
- Authentication and authorization decisions (users, devices, agent principal)
- Telemetry validation, dedupe, ordering, storage in PostgreSQL and ClickHouse
- Deterministic incident rules and thresholds
- Command lifecycle, **safety policy**, approval enforcement, outbox, idempotency
- MQTT publish of commands/config; consumption of acks
- Realtime fan-out to the browser
- Metrics, traces, structured logs

Must not: call an LLM, embed prompts, or depend on the agent for any safety decision.

### 2.2 Python (`agent-service`)
Owns:
- LangGraph workflow state and checkpoints (own schema `agent` in PostgreSQL)
- Prompting, tool selection, structured diagnosis
- Document ingestion, chunking, embeddings, retrieval, citation checks (tables `docs.*`)
- Agent evaluation harness

Reads evidence **only through the Rust API** using a per-run, scoped token. May *request* a command; cannot approve, execute, or bypass policy. Reports progress by posting events to `hub-api`.

Must not: connect to MQTT, write to Rust-owned tables, hold device credentials, or decide thresholds.

### 2.3 Next.js (`web`)
Owns:
- Rendering, navigation, filtering, charts, client-side caching
- Subscribing to SSE streams, reconnect with `Last-Event-ID`
- Collecting approve/reject decisions and sending them to `hub-api`

Must not: contain business rules, authorization logic beyond hiding UI, or talk to the agent service or databases directly.

### 2.4 Firmware and bridge
- **Firmware** owns motor control, line-following, obstacle stop, speed limits, comms-loss stop, e-stop. It re-validates every command regardless of upstream approval.
- **Bridge** owns the serial port, framing, MQTT connection with the device credential, store-and-forward, and an allow-list of command types. It does not interpret or route business logic.

## 3. Interfaces

| From → To | Interface | Contract |
|---|---|---|
| Device/bridge ↔ Broker | MQTT 3.1.1/5, TLS | [EVENT_CONTRACTS](EVENT_CONTRACTS.md) |
| Broker → `hub-worker` | MQTT subscribe (shared subscription for scale-out) | Telemetry, status, ack |
| `hub-api`/`hub-worker` → Broker | MQTT publish | Commands, config |
| `web` → `hub-api` | REST (JSON) + SSE | OpenAPI generated from Rust code |
| `agent-service` → `hub-api` | REST with scoped agent token | Same OpenAPI, `/v1/agent/*` and read endpoints |
| `hub-api` → `agent-service` | `POST /investigations` (start/resume), HMAC-signed | Starts workflow for an incident |
| `agent-service` → `hub-api` | `POST /internal/agent-events` | Progress, tool calls, evidence, diagnosis |
| Services → DBs | SQLx (PostgreSQL), ClickHouse HTTP | Ownership in [DATA_MODEL](DATA_MODEL.md) |

## 4. Data ownership

| Store / schema | Writer | Readers |
|---|---|---|
| PostgreSQL `core.*` (tenants, devices, commands, incidents, audit, outbox) | Rust only | Rust |
| PostgreSQL `agent.*` (LangGraph checkpoints, runs) | Python only | Python; Rust read-only for run status |
| PostgreSQL `docs.*` (documents, chunks, embeddings) | Python only | Python |
| ClickHouse `telemetry.*` | `hub-worker` only | `hub-api` (queries) |

Agents never get direct SQL access to `core.*` or ClickHouse.

## 5. Authority and failure ownership

| Concern | Authority |
|---|---|
| Is this user/agent/device allowed? | `hub-api` (service) and broker ACL (device) |
| Is this command safe now? | `hub-api` policy gate; then bridge allow-list; then firmware |
| Is this an incident? | `hub-worker` rules |
| What probably caused it? | `agent-service` (advisory only) |
| What do we show? | `web` |

If `agent-service` is down, incidents still open, operators still approve and send commands manually. If the LLM is down, the graph returns a degraded diagnosis built from deterministic evidence.

## 6. Repository layout

```
devicehub/
  crates/            # Rust workspace: api, worker, common (domain, db, mqtt, policy), simulator, bridge
  agent/             # Python: graph, tools, rag, evals
  web/               # Next.js
  firmware/          # Arduino sketch(es)
  deploy/            # compose files, broker config, otel, prometheus, grafana
  docs/              # ADRs, benchmarks, diagrams
  migrations/        # core (SQLx) and clickhouse SQL
```

Shared logic that must not diverge (e.g. command catalog and limits) lives in `crates/common` and is exported as JSON Schema/OpenAPI for Python and TypeScript to consume.
