# DeviceHub AI

DeviceHub AI is an **additive extension** to this repository's existing Agentic Knowledge Base. It adds an IoT / fleet-operations domain that reuses the existing retrieval and agent capabilities. The Knowledge Base must remain independently demonstrable and is not replaced, renamed, or refactored by DeviceHub work.

| | |
|---|---|
| Status | Phase 1 / S0 Foundations (design baseline) |
| Design baseline | `docs/DeviceHub/` on `feat/devicehub-phase-1-foundation` |
| Host repository | `enterprise-agentic-knowledgebase` (pnpm + Turborepo monorepo) |
| Hardware | `[HW-TBD]` — see [HARDWARE_INVENTORY](HARDWARE_INVENTORY.md) |

The rule of thumb throughout these documents: **Rust owns truth and safety, Python owns reasoning, Next.js owns presentation.**

## Document map

| Document | Purpose |
|---|---|
| [PRD](PRD.md) | Problem, personas, user stories, functional and non-functional requirements |
| [PROJECT_SCOPE](PROJECT_SCOPE.md) | Slices S0–S5, MVP boundary, exclusions, success criteria |
| [SERVICE_BOUNDARIES](SERVICE_BOUNDARIES.md) | Deployable units, responsibilities, interfaces, data ownership |
| [DATA_MODEL](DATA_MODEL.md) | PostgreSQL `core`/`agent`/`docs` schemas, ClickHouse `telemetry`, retention |
| [EVENT_CONTRACTS](EVENT_CONTRACTS.md) | MQTT topics, payload schemas, command catalog, SSE events |
| [WORKFLOWS](WORKFLOWS.md) | Ingestion, incident investigation, command approval state machines |
| [SECURITY](SECURITY.md) | Trust boundaries, authn/authz, tenant isolation, agent and device safety |
| [LOCAL_DEVELOPMENT](LOCAL_DEVELOPMENT.md) | Compose, environment variables, migrations, run commands |
| [HARDWARE_INVENTORY](HARDWARE_INVENTORY.md) | Component inventory, unknowns, and bench tests still required |
| [REPOSITORY_INTEGRATION](REPOSITORY_INTEGRATION.md) | How the logical DeviceHub layout maps onto this monorepo |
| [LLM_IMPLEMENTATION_GUIDE](LLM_IMPLEMENTATION_GUIDE.md) | Operating instructions for coding agents, phase authorization, stop conditions |
| [PHASE_1_REPORT](PHASE_1_REPORT.md) | Phase 1 / S0 deliverables, findings, and measured baseline results |
| [Architecture (HTML)](../DeviceHub%20AI%20—%20Architecture.html) | Interactive architecture diagram |

## Architecture decisions

The ADR index lives in [adr/README.md](adr/README.md) — 0001–0012 define the platform, 0013 records how DeviceHub is hosted inside the existing Agentic RAG monorepo.

Accepted decisions that are easy to violate by accident:

- **ADR-0002** — Rust owns the device plane; Python owns reasoning. Python never reads or writes Rust-owned tables.
- **ADR-0004** — PostgreSQL for the first telemetry slice; ClickHouse only in S2, only after a measured Postgres baseline, never authoritative for safety.
- **ADR-0005** — the LLM can only *request* commands. No LLM output reaches motor pins, thresholds, or approvals.
- **ADR-0007** — every command has an idempotency key, an `expires_at`, and a `target_boot_id`.
- **ADR-0009** — tenant comes from the authenticated principal, never from topics, bodies, or model output.
- **ADR-0013** — DeviceHub lives inside the existing monorepo; it is not a second repository or a second copy of the app.

## Current phase

**Only Phase 1 / S0 Foundations is authorized.** That phase is inventory, documentation, and contract review. It does not implement the Rust service, MQTT flow, database migrations, simulator, firmware, agent tools, or dashboard pages. See [LLM_IMPLEMENTATION_GUIDE](LLM_IMPLEMENTATION_GUIDE.md) §5 and [PHASE_1_REPORT](PHASE_1_REPORT.md).

## Related host-project documents

The Agentic Knowledge Base keeps its own authority chain, unchanged: `docs/PRD.md` → `docs/adr/` → `docs/specs/` → `docs/conventions.md`. DeviceHub documents must not override them for existing functionality.
