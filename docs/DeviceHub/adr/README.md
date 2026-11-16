# Architecture Decision Records

Each ADR records one significant decision: context, the decision, alternatives, and consequences. Status values: **Proposed**, **Accepted**, **Superseded by ADR-n**. Decisions marked *revisit* name the evidence that would change them.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-modular-monorepo.md) | Modular monorepo with few deployable units | Accepted |
| [0002](0002-rust-device-plane-python-agent-plane.md) | Rust for the device plane, Python for the agent plane | Accepted |
| [0003](0003-mosquitto-broker.md) | Mosquitto as the MQTT broker (EMQX as migration path) | Accepted |
| [0004](0004-postgres-clickhouse-pgvector.md) | PostgreSQL + ClickHouse + pgvector | Accepted |
| [0005](0005-deterministic-safety-llm-requests-only.md) | Deterministic safety; the LLM can only request | Accepted |
| [0006](0006-telemetry-at-least-once-idempotent.md) | At-least-once telemetry with idempotent processing | Accepted |
| [0007](0007-command-outbox-idempotency-expiry.md) | Command delivery via transactional outbox, idempotency and expiry | Accepted |
| [0008](0008-arduino-host-bridge.md) | Connect the Arduino through a host bridge | Accepted (provisional, hardware TBD) |
| [0009](0009-tenant-isolation-rls.md) | Tenant isolation with identity-derived tenant and PostgreSQL RLS | Accepted |
| [0010](0010-json-payloads-v1.md) | JSON payloads with explicit schema versions in v1 | Accepted (revisit after benchmark) |
| [0011](0011-single-langgraph-agent.md) | One investigation agent on LangGraph | Accepted |
| [0012](0012-sse-for-realtime.md) | Server-Sent Events for browser realtime | Accepted |
| [0013](0013-devicehub-within-agentic-rag-monorepo.md) | Host DeviceHub inside the existing Agentic RAG monorepo | Accepted |
| [0014](0014-single-process-rust-deploy.md) | Deploy the Rust device plane as one process on Render's free tier | Accepted |

## Template

```
# ADR-NNNN: Title
Status · Date
## Context
## Decision
## Alternatives considered
## Consequences (positive / negative / risks)
## Revisit when
```
