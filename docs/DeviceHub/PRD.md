# DeviceHub AI — Product Requirements Document

| | |
|---|---|
| Status | Draft v0.1 |
| Owner | Amit |
| Related | [PROJECT_SCOPE](PROJECT_SCOPE.md) · [SERVICE_BOUNDARIES](SERVICE_BOUNDARIES.md) · [DATA_MODEL](DATA_MODEL.md) · [EVENT_CONTRACTS](EVENT_CONTRACTS.md) · [WORKFLOWS](WORKFLOWS.md) · [SECURITY](SECURITY.md) · [ADRs](adr/README.md) |

Hardware-specific items are **provisional** until the component inventory is complete. They are marked `[HW-TBD]`. Current inventory, unknowns, and required bench tests: [HARDWARE_INVENTORY](HARDWARE_INVENTORY.md).

## 1. Problem

Operating a fleet of connected devices requires more than collecting data. Operators need to know which devices are online, what they report, when something is wrong, why it is wrong, and how to fix it safely. Today that means tailing logs, reading manuals, and sending ad-hoc commands with no audit trail.

DeviceHub AI is a device-management platform that:

1. ingests telemetry reliably at volume,
2. detects incidents with deterministic rules,
3. lets a bounded AI agent investigate incidents using evidence and device documentation,
4. routes any consequential device action through human approval and backend safety validation.

It is demonstrated with one **real Arduino robot** and a **simulated fleet** for load.

## 2. Goals and non-goals

**Goals**
- G1. A real robot publishes telemetry and executes safe, validated, acknowledged commands.
- G2. The backend ingests, stores, queries and visualizes telemetry from the robot plus simulated devices, without losing or double-applying events.
- G3. Incidents are detected deterministically and investigated by a stateful, observable agent.
- G4. Every consequential action is authorized, approved by a human, re-validated by the backend, audited, and executed at most once.
- G5. Performance and agent quality are backed by reproducible measurements.

**Non-goals** — see [PROJECT_SCOPE §4](PROJECT_SCOPE.md#4-exclusions-non-goals).

## 3. Users

| Persona | Needs |
|---|---|
| **Operator** | See fleet health, react to incidents, approve or reject proposed actions. |
| **Admin** | Register devices, rotate credentials, manage users and tenant settings. |
| **Viewer** | Read-only fleet and incident visibility. |
| **Device** | Authenticate, publish telemetry, receive and acknowledge commands. |
| **Agent** (service principal) | Read evidence and *request* actions within narrow scopes. |
| **Developer/Reviewer** (secondary) | Run the system locally, read decisions, reproduce benchmarks. |

## 4. User stories

IDs are referenced by requirements and tests.

- **US-1** As an operator, I see all devices with online/offline status and latest readings.
- **US-2** As an operator, I open a device and see live and historical telemetry for a chosen time range.
- **US-3** As an admin, I register a device and receive credentials once, and can rotate or revoke them.
- **US-4** As an operator, I am shown an incident when the robot detects an obstacle, a sensor misbehaves, or a device disconnects.
- **US-5** As an operator, I watch an AI investigation progress (tool calls, evidence, citations) and read a structured diagnosis.
- **US-6** As an operator, I approve or reject a proposed command, and see its outcome.
- **US-7** As an operator, I can stop a device immediately.
- **US-8** As an admin, I can see who did what: commands, approvals, configuration changes.
- **US-9** As a developer, I start the whole stack with one command and run a simulated fleet.
- **US-10** As a reviewer, I reproduce a benchmark and an agent evaluation run from the repo.

## 5. Functional requirements

Priority: **P0** = first vertical slice / MVP, **P1** = MVP complete, **P2** = stretch.

### 5.1 Device management
| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| FR-1 | Register devices with metadata, kind (`real`/`simulated`), tenant. | P0 | Created device appears in list; duplicate external ID rejected. |
| FR-2 | Per-device credentials, stored hashed, shown once, rotatable with an overlap window, revocable. | P0 | Revoked credential cannot connect within the broker sync interval; rotation causes no telemetry gap. |
| FR-3 | Online/offline via MQTT last-will plus heartbeat timeout. | P0 | Device killed uncleanly shows offline within the configured timeout. |
| FR-4 | Latest-state API per device. | P0 | Reflects newest in-order event, ignores stale ones. |
| FR-5 | Versioned device configuration with acknowledgment and status. | P1 | Config shows `pending → acked/rejected`; devices report applied version. |

### 5.2 Telemetry
| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| FR-6 | Ingest versioned telemetry over MQTT. | P0 | Valid events land in Postgres latest-state; invalid ones go to the dead-letter table with a reason. |
| FR-7 | Handle duplicate, delayed, malformed and out-of-order events. | P0 | Fault-injection tests: duplicates stored once; stale events do not overwrite latest state. |
| FR-8 | Bounded queues, batching and backpressure with documented shedding policy. | P1 | Under overload, memory stays bounded and drop counters increment; no panic. |
| FR-9 | Historical storage in ClickHouse; time-range query API with cursor pagination and bounded windows. | P1 | Query beyond max window is rejected with a structured error. |
| FR-10 | Aggregations (min/avg/max per bucket) and fleet-level analytics. | P1 | Rollup results match raw-query results on a fixed dataset. |

### 5.3 Commands
| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| FR-11 | Create commands from a fixed, typed catalog. Idempotency key, expiry, per-device queueing. | P0 | Same key returns the same command; expired commands are never delivered. |
| FR-12 | Delivery, acknowledgment and execution status tracking. | P0 | `acked` and `completed/failed` states recorded with timestamps. |
| FR-13 | Commands to offline devices are retained, not lost; stale ones expire. | P1 | Command created offline is delivered on reconnect if not expired. |
| FR-14 | Risk-classified policy: movement-enabling commands require human approval; risk-reducing (`stop`) may auto-approve. | P0 | Policy table has tests; the agent cannot approve. |
| FR-15 | Backend re-validates after approval. | P0 | Approved command that violates current limits is rejected and audited. |
| FR-16 | Exactly-once effect under restart and retry. | P1 | Crash-injection test never produces two executions. |
| FR-17 | Immediate stop path (emergency stop). | P0 | Stop reaches the device regardless of queue state; the MCU also stops on comms loss. |

### 5.4 Incidents and agent
| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| FR-18 | Deterministic rules for obstacle, sensor range/flatline, disconnect, simulated anomaly. | P0/P1 | Rule tests replay recorded traces; hysteresis prevents flapping. |
| FR-19 | Incident lifecycle with severity, status, timestamps and evidence. | P1 | State transitions enforced; evidence is append-only. |
| FR-20 | Agent investigation workflow (LangGraph) with checkpointing and budgets. | P1 | Workflow resumes after a service restart and respects step/time/token caps. |
| FR-21 | Narrow tools: device status, telemetry history, incidents, diagnostics search, request-command. | P1 | Tools cannot execute commands; scopes enforced server-side. |
| FR-22 | RAG over manuals with metadata filters, hybrid retrieval and citations. | P1 | Diagnosis cites retrieved passages; citation checker flags unsupported claims. |
| FR-23 | Verify command outcome and append to the incident. | P1 | Incident shows pre/post evidence for an executed command. |
| FR-24 | Prompt-injection resistance for untrusted documents and tool outputs. | P1 | Injection test corpus produces zero unsafe command requests. |
| FR-25 | MCP server exposing selected capabilities. | P2 | Same authorization and policy as the HTTP tools. |

### 5.5 Dashboard
| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| FR-26 | Fleet overview, device list/filters, device detail, live telemetry (SSE). | P0/P1 | Updates appear without reload; reconnect resumes. |
| FR-27 | Incident center with severity/status filters and investigation view. | P1 | Shows tool activity, evidence, citations. |
| FR-28 | Approval center and command history. | P1 | Approve/reject is audited and reflected live. |
| FR-29 | Config versions and audit events. | P1 | Filterable by device, actor, time. |
| FR-30 | Historical charts and fleet analytics. | P1 | Large ranges are downsampled server-side. |

## 6. Non-functional requirements

Targets marked *(initial)* are starting points; they are revised after the first recorded baseline. Every benchmark records hardware, dataset, event rate and conditions.

| Area | Requirement |
|---|---|
| Safety | No LLM output reaches motor pins. Robot stops on obstacle, on comms loss, and on `stop`/`estop`, enforced on the MCU. |
| Reliability | At-least-once delivery with idempotent processing; no duplicate command execution; graceful shutdown drains in-flight work. |
| Performance *(initial)* | Sustain 5,000 simulated telemetry msgs/s on a single dev machine with bounded memory; telemetry visible in dashboard p95 < 1 s end-to-end. |
| Query *(initial)* | Latest-state p95 < 50 ms; 24 h single-device range query p95 < 300 ms on a stated dataset. |
| Security | Tenant isolation on every store; device credentials least-privilege; full audit of commands and approvals. See [SECURITY](SECURITY.md). |
| Observability | Correlation IDs and traces across HTTP, MQTT, DB and agent steps; metrics for lag, queue depth, drops, command outcomes. |
| Agent quality | ≥ 50 scenarios; measure diagnosis quality, tool selection, citation correctness, unsafe action attempts, latency, cost. Unsafe actions executed = 0. |
| Operability | Whole stack runs via Docker Compose; CI checks format, lint, tests, migrations and builds. |

## 7. Success metrics

See [PROJECT_SCOPE §5](PROJECT_SCOPE.md#5-success-criteria). Summary: working real device, reproducible benchmarks, passing agent eval suite, zero unsafe executions in fault and injection tests.

## 8. Assumptions

- A1. A host computer (laptop or Raspberry Pi class) is available to bridge USB serial to MQTT. `[HW-TBD]`
- A2. Arduino board has enough pins/timers for sensors and a motor driver; no on-board network stack is assumed.
- A3. A single tenant is enough for the physical demo; multi-tenancy is proven with simulated tenants.
- A4. An LLM API is available for the agent; the agent degrades gracefully without it.

## 9. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Scope too wide | Nothing finishes | Vertical-slice order; P0 list; one agent only. |
| Hardware surprises (power, noise, pinouts) | Delays Phase 4 | Phase 1 inventory; bench-test with motors lifted; simulator keeps backend work unblocked. |
| Robot behaves unsafely during demo | Damage/injury | MCU-enforced limits, speed caps, comms-loss stop, tested e-stop. |
| Agent hallucinated diagnosis | Misleading operators | Citations required, evidence-only prompts, eval suite, human approval. |
| Prompt injection via docs/tool output | Unsafe command requests | Untrusted-data handling, allow-listed command catalog, backend policy. |
| Benchmark numbers not credible | Weak portfolio signal | Record environment; commit raw results; compare strategies, not just report one number. |

## 10. Open questions

1. Exact Arduino board, motor driver, sensors, power supply `[HW-TBD]`.
2. Bridge host: laptop, Raspberry Pi, or an ESP-class network module later?
3. LLM provider/model for the agent, and evaluation judge approach.
4. Whether to adopt a binary payload format after the first throughput benchmark ([ADR-0010](adr/0010-json-payloads-v1.md)).
5. User auth for MVP: local accounts vs external identity provider ([SECURITY §2](SECURITY.md#2-authentication)).
