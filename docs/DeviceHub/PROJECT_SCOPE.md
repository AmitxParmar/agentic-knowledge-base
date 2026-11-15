# PROJECT_SCOPE

Features, MVP, exclusions and success criteria for DeviceHub AI. Requirement IDs (FR-n) refer to the [PRD](PRD.md).

## 1. One-paragraph scope

DeviceHub AI is a modular-monorepo IoT platform. A Rust backend ingests MQTT telemetry from one real Arduino robot and many simulated devices, stores state in PostgreSQL and history in ClickHouse, detects incidents with deterministic rules, and exposes a Next.js dashboard. A Python/LangGraph agent investigates incidents with RAG and narrow tools, and can only *request* actions that pass human approval and backend safety validation.

## 2. Build order (vertical slices)

Rule: finish a slice end to end before starting the next. Phase numbers match the project plan.

| Slice | Phases | What is demonstrable |
|---|---|---|
| **S0 Foundations** | 1 | Component inventory, wiring diagram, schemas, repo and docs |
| **S1 First vertical slice** | 2, 3 (core), 4 | Real robot → bridge → Mosquitto → Rust ingest → PostgreSQL latest state; robot receives a validated `stop` and acks |
| **S2 Platform depth** | 3 (rest), 5, 6 | Simulator at scale, ClickHouse history, command lifecycle, config versions, queries |
| **S3 Intelligence** | 7 | Rules → incidents → LangGraph investigation → approval → verified outcome |
| **S4 Experience** | 8 | Full dashboard with live telemetry, incidents, approvals, audit |
| **S5 Hardening** | 9, 10 | Observability, chaos tests, security docs, benchmarks, eval suite, demo |

## 3. Features

### MVP (P0) — S1
- Device registry, hashed credentials, tenant column everywhere
- MQTT topics and v1 telemetry schema, ingest worker with dedupe and dead-letter table
- Latest state and online/offline
- Robot firmware: line follow, ultrasonic obstacle stop, speed limits, comms-loss stop
- Host bridge: serial ⇄ MQTT
- Command catalog `stop`, `estop` with ack/status
- Policy gate (approve/reject rules) with tests
- Minimal dashboard: device list + latest readings (live via SSE)
- Docker Compose for broker, Postgres, backend

### MVP complete (P1) — S2–S4
- Simulator with fault injection; ClickHouse history; aggregation and range APIs
- Full command lifecycle: idempotency, expiry, offline queueing, outbox, approval
- Versioned config with acknowledgments; audit log
- Rules engine and incident lifecycle
- LangGraph investigation agent, scoped tools, RAG with citations, verification step
- Incident center, approval center, charts, audit views
- OpenTelemetry, Prometheus, Grafana, Langfuse
- k6/MQTT load tests, ≥ 50 agent scenarios, CI

### Stretch (P2)
- MCP server for selected tools
- DuckDB offline analysis and Parquet export
- OTA firmware update with rollback
- Binary payload format benchmark (see [ADR-0010](docs/adr/0010-json-payloads-v1.md))
- EMQX migration experiment (see [ADR-0003](docs/adr/0003-mosquitto-broker.md))

## 4. Exclusions (non-goals)

- Multi-agent systems or agent-to-agent delegation (one reliable agent first)
- LLM involvement in motor control, thresholds, or safety-critical decisions
- Kubernetes, service mesh, multi-region deployment (Docker Compose only)
- Splitting into many microservices without a measured operational reason
- Mobile apps, billing, SSO/SCIM, public self-serve signup
- Video/camera streams, SLAM, autonomous navigation beyond line following and obstacle stop
- Training or fine-tuning models
- Production hardware certification; the robot is a prototype used only in a controlled setting
- Custom MQTT broker implementation or custom time-series database

## 5. Success criteria

Each criterion is checkable. Numeric targets are *initial* and are revised after the first recorded baseline; the method (recorded hardware, dataset, rate) is fixed.

### Functional
- [ ] Physical robot publishes telemetry and acknowledges validated commands end to end
- [ ] Simulated fleet runs independently of the robot
- [ ] Telemetry is ingested, stored, queried and visualized
- [ ] An incident is detected, investigated by the agent, and a proposed action is approved, executed and verified
- [ ] Every command and approval has an audit record

### Safety and correctness
- [ ] Robot stops on obstacle, `stop`/`estop`, and loss of communication, tested on hardware
- [ ] Duplicate-event, stale-command and crash-restart tests show no double execution
- [ ] Prompt-injection corpus yields zero unsafe command requests; unsafe actions executed = 0
- [ ] LLM output never reaches motor pins (verified by code boundary and tests)

### Performance (initial targets)
- [ ] 5,000 simulated msgs/s sustained on a stated dev machine with bounded memory
- [ ] Dashboard end-to-end telemetry latency p95 < 1 s at that rate
- [ ] Comparison table: single-row insert vs batch vs buffered writes; Postgres vs ClickHouse query workloads
- [ ] p50/p95/p99, CPU and memory recorded for each benchmark with full conditions

### Agent quality
- [ ] ≥ 50 evaluation scenarios, run in CI
- [ ] Reported: diagnosis quality, tool selection, task completion, citation correctness, unsafe attempts, latency, cost

### Delivery
- [ ] One-command local start; CI green on format, lint, tests, migrations, builds
- [ ] Setup guide, API docs, ADRs, demo scenarios, short end-to-end demo, published benchmark results

## 6. Definition of done

Matches the project definition of done: a safe real robot, independent simulated load, an ingest-store-query-visualize pipeline, a stateful investigation workflow, authorized and human-approved consequential actions, observable and auditable failures, and reproducible measurements.

## 7. Scope change rule

A new feature enters the scope only if it (a) supports a success criterion above, or (b) replaces something of equal size. Record the decision in an ADR or in this file's change log.
