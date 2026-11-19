# DeviceHub AI: LLM Implementation Guide

**Purpose:** a single set of operating instructions for coding agents (Codex, Claude Code, Cursor, or another LLM coding agent) extending the existing Agentic RAG monorepo with DeviceHub AI.

This guide does not replace the design documents in this directory. Those remain the source of truth; this file defines process, authorization, and stop conditions.

---

## 1. Project context

This repository already contains a working Agentic Knowledge Base / Agentic RAG project. DeviceHub AI is an **additive extension** to it.

The goal is to preserve the existing project as a separately demonstrable portfolio product while adding an IoT and fleet-operations domain that reuses the existing AI capabilities.

Responsibility split:

- **Existing Next.js app (`apps/web`):** preserve the current chat UI, streaming, citations, and user experience. Add DeviceHub screens later without replacing existing routes or components.
- **Existing Python/FastAPI app (`apps/api`):** preserve document ingestion, extraction, chunking, embeddings, hybrid retrieval, reranking, citations, and the existing research workflow. Later add a separate DeviceHub investigation graph that reuses stable RAG capabilities.
- **New Rust application:** own the DeviceHub device plane — device APIs, telemetry processing, incidents, command policy, and device communication — as those capabilities are implemented.
- **MQTT broker:** device event transport, using Mosquitto as specified in the existing ADRs.
- **PostgreSQL:** reuse the existing infrastructure where practical, with clear ownership of existing RAG tables and new DeviceHub tables.
- **Arduino/host bridge and simulator:** later device sources. Hardware details remain provisional until the physical inventory is confirmed.

Design principle: **Rust owns truth and safety, Python owns reasoning, Next.js owns presentation.** The physical layout adaptation is recorded in [ADR-0013](adr/0013-devicehub-within-agentic-rag-monorepo.md) and [REPOSITORY_INTEGRATION](REPOSITORY_INTEGRATION.md).

## 2. Source-of-truth documents

Before making any change, read:

- [PRD](PRD.md)
- [PROJECT_SCOPE](PROJECT_SCOPE.md)
- [SERVICE_BOUNDARIES](SERVICE_BOUNDARIES.md)
- [DATA_MODEL](DATA_MODEL.md)
- [EVENT_CONTRACTS](EVENT_CONTRACTS.md)
- [WORKFLOWS](WORKFLOWS.md)
- [SECURITY](SECURITY.md)
- [LOCAL_DEVELOPMENT](LOCAL_DEVELOPMENT.md)
- [REPOSITORY_INTEGRATION](REPOSITORY_INTEGRATION.md)
- [HARDWARE_INVENTORY](HARDWARE_INVENTORY.md)
- [adr/README.md](adr/README.md) and the relevant ADRs:
  - [0001](adr/0001-modular-monorepo.md), [0002](adr/0002-rust-device-plane-python-agent-plane.md), [0003](adr/0003-mosquitto-broker.md), [0004](adr/0004-postgres-clickhouse-pgvector.md), [0005](adr/0005-deterministic-safety-llm-requests-only.md), [0006](adr/0006-telemetry-at-least-once-idempotent.md), [0007](adr/0007-command-outbox-idempotency-expiry.md), [0008](adr/0008-arduino-host-bridge.md), [0009](adr/0009-tenant-isolation-rls.md), [0010](adr/0010-json-payloads-v1.md), [0011](adr/0011-single-langgraph-agent.md), [0012](adr/0012-sse-for-realtime.md), [0013](adr/0013-devicehub-within-agentic-rag-monorepo.md)

Also read the host project's own authority chain: root `AGENTS.md`, `docs/PRD.md`, `docs/adr/`, `docs/specs/`, and `docs/conventions.md`.

## 3. How to handle conflicts or gaps

1. Treat the existing PRD, scope, service boundaries, data model, event contracts, workflows, security document, and ADRs as the design baseline.
2. Do not silently invent a new architecture or silently rewrite a documented decision.
3. Adapt implementation paths to the existing monorepo while preserving the documented logical boundaries.
4. If an adaptation materially changes a decision, propose a small ADR update and explain why. Do not rewrite all documentation.
5. If two documents genuinely conflict, identify the exact conflict and ask before making a consequential choice.
6. Mark unknowns as `TBD` or `[HW-TBD]`. Do not guess hardware models, pinouts, voltage, networking capability, or measured performance.

Known contract inconsistencies are tracked in [PHASE_1_REPORT](PHASE_1_REPORT.md) §5. Do not "fix" them by editing the contracts without a decision.

## 4. Non-negotiable preservation rules

- Never delete, rename, move, replace, or rewrite existing Agentic Knowledge Base files or functionality as part of DeviceHub work.
- Do not refactor the existing RAG pipeline to accommodate DeviceHub.
- Do not remove or regress the existing chat UI, streaming, citations, document ingestion, retrieval, reranking, agent workflow, or deployment.
- Do not replace the existing package manager, workspace tooling, lockfiles, CI, Docker setup, environment variable names, or deployment configuration.
- Do not run destructive database commands, reset existing databases, drop schemas, or rewrite existing migrations.
- Do not access Rust-owned DeviceHub tables directly from Python. Python calls the Rust API for device evidence.
- Do not let an LLM control motor pins, choose safety thresholds, approve commands, or bypass backend policy.
- Do not introduce ClickHouse, RabbitMQ, Kafka, Kubernetes, or additional services before the phase that needs them. Redis already exists and is not a new dependency.
- Do not assume the Arduino components work. Physical hardware work is blocked until the inventory and bench tests establish what works.
- Never push, merge, deploy, force-push, amend shared history, or modify the default branch without explicit user authorization.

## 5. Required workflow for every task

Before coding:

1. Run `git status --short --branch` and inspect the current diff.
2. Read root `AGENTS.md` and any nested instruction files that apply to the files being changed.
3. Read the relevant DeviceHub docs and ADRs.
4. Inspect the actual monorepo structure, package manager, scripts, environment conventions, Compose files, migrations, tests, and CI.
5. State the intended files to add/change and explain whether existing behavior is affected.
6. If the working tree contains uncommitted changes that could be affected, stop and ask. Never discard or overwrite user work.

While coding:

- Make small, additive, reviewable changes.
- Follow existing repository conventions rather than imposing a new layout.
- Keep DeviceHub code isolated in new directories/modules where practical.
- Avoid speculative abstractions and placeholder modules with no implementation value.
- Do not implement future phases early.
- Keep secrets out of source control and logs.
- Do not claim tests passed unless they were actually run.

After coding:

1. Run focused tests and relevant existing regression tests.
2. Run formatting, lint, type-check, and build commands relevant to changed code.
3. Run `git diff --check` and inspect the complete diff.
4. Report files added/changed, commands executed, test results, failures, assumptions, and remaining risks.
5. Stop at the requested phase boundary.

## 6. Phase plan and current authorization

Build order per [PROJECT_SCOPE](PROJECT_SCOPE.md) §2: S0 Foundations, S1 First vertical slice, S2 Platform depth, S3 Intelligence, S4 Experience, S5 Hardening.

**Only Phase 1 / S0 Foundations is authorized.** Do not start Phase 2 or implement the first telemetry vertical slice until the user explicitly asks.

### Phase 1 / S0: Foundations

S0 covers component inventory, wiring diagram (only where hardware is known), schemas, repository setup, and documentation. Its purpose is to remove uncertainty and prepare the monorepo for later Rust/device implementation. It is not the implementation of the DeviceHub backend.

#### A. Inspect and protect the existing project

- Inspect the repository root, branch, latest commit, working tree, and uncommitted changes.
- Read root and nested `AGENTS.md` files.
- Map the existing Next.js and FastAPI app paths, shared packages, workspace tooling, Docker, environment files, database migrations, CI, and deployment.
- Record the current Knowledge Base baseline and its working commands.
- Create the annotated tag `agentic-knowledgebase-v1.0.0` only when the tree is clean and the commit is a suitable baseline. If the tag exists, do not move it. If the tree is dirty or the baseline is unclear, stop and ask.
- Create the feature branch `feat/devicehub-phase-1-foundation` from the verified baseline. If it exists, inspect it; never overwrite it.
- Do not push or merge unless asked.

Suggested Git sequence, only after confirming the tree is clean and the baseline is appropriate:

```bash
git status --short --branch
git log -1 --oneline
git tag -a agentic-knowledgebase-v1.0.0 -m "Standalone Agentic Knowledge Base baseline"
git switch -c feat/devicehub-phase-1-foundation
```

Do not run the tag command if the tag already exists.

#### B. Inventory physical hardware

See [HARDWARE_INVENTORY](HARDWARE_INVENTORY.md). Record, without guessing: board make and model, motor driver model, ultrasonic sensor model, line-sensor type and count, motors and chassis, power supply ratings, USB/serial connectivity, network module, pin labels, datasheets, and physical condition.

Use statuses `unknown`, `not inspected`, `needs testing`, `working`, `not working`, `missing`. Do not buy parts or design final wiring from assumptions. Ask for the specific missing fact instead of inventing it.

#### C. Define the physical integration boundary

- Read ADR-0008. The documented provisional approach is Arduino → host serial bridge → MQTT. It stays provisional until the board and connectivity are known.
- Identify what can be decided now and what depends on the inventory.
- Do not flash firmware, drive motors, or issue movement commands in Phase 1.
- Do not produce a final pin-by-pin wiring diagram until board, driver, sensor, motor, and power details are verified.
- Record the safety assumptions: motor control and e-stop behavior remain deterministic on the microcontroller; the LLM never controls pins.

#### D. Review and freeze interface contracts

Read [DATA_MODEL](DATA_MODEL.md), [EVENT_CONTRACTS](EVENT_CONTRACTS.md), and [WORKFLOWS](WORKFLOWS.md).

- Check that telemetry and command schemas are internally consistent.
- Confirm required identifiers, schema versions, timestamps, event IDs, idempotency keys, expiry fields, and acknowledgment states are represented.
- Check topic names and publisher/subscriber responsibilities against [SERVICE_BOUNDARIES](SERVICE_BOUNDARIES.md) and ADR-0003.
- Record open questions and contradictions. Do not implement schemas or migrations in this phase.
- Do not invent sample telemetry fields that confirmed hardware cannot produce. Mark generic/simulator examples as examples.

#### E. Adapt repository documentation to the existing monorepo

- Preserve all DeviceHub docs in `docs/DeviceHub/`.
- Update only statements that incorrectly assume a standalone repository.
- Do not move existing Agentic RAG apps into a new layout.
- Add a short section to the root `README.md` explaining that DeviceHub is an extension and the Knowledge Base remains available.
- Keep the existing Knowledge Base documentation and entry point intact.
- If the integration changes an accepted decision, add one focused ADR (done: ADR-0013).

#### F. Confirm local development prerequisites

- Record installed versions of Rust, Node/pnpm, Python/uv, Docker, and Compose.
- Inspect existing database setup. Reuse it where possible.
- Do not add a second PostgreSQL container if the existing database can be reused with isolated schemas and non-destructive migrations.
- Review [LOCAL_DEVELOPMENT](LOCAL_DEVELOPMENT.md) against the monorepo. Mark planned commands as planned; do not claim they exist.
- Do not add ClickHouse in Phase 1.
- Do not add Rust application code, MQTT consumers, database migrations, simulator code, agent tools, or frontend routes unless the user explicitly expands Phase 1 scope.

### Phase 1 deliverables

1. A repository map: web app, Python API, shared packages, docs, Docker, migrations, CI.
2. The original branch and baseline commit.
3. Whether the V1 tag was created, already existed, or was deferred.
4. The new feature branch name.
5. A hardware inventory with unknowns explicitly marked.
6. The hardware tests still needed from the user.
7. A review of data/event/workflow contracts, with inconsistencies and unresolved questions.
8. Documentation changes made and why.
9. A verified local prerequisites report.
10. Knowledge Base baseline checks and their results.
11. Decisions that must wait for Phase 2.
12. Confirmation that no existing RAG feature, schema, application, or deployment was removed or rewritten.

All twelve are recorded in [PHASE_1_REPORT](PHASE_1_REPORT.md).

### Phase 1 acceptance criteria

- Existing Agentic Knowledge Base remains intact.
- Work is isolated on `feat/devicehub-phase-1-foundation`.
- Baseline tag handled without overwriting an existing tag.
- Hardware facts are inventoried or explicitly left unknown.
- No unsafe hardware action is performed.
- Existing contracts and ADRs have been reviewed for consistency.
- Repository-specific setup instructions reflect the real monorepo.
- Existing project checks are run and reported honestly.
- No Phase 2 implementation has started.

**Stop after Phase 1 and wait for user approval.**

### Explicitly prohibited in Phase 1

Do not implement Rust business logic or a new Rust service, MQTT producers/consumers, PostgreSQL migrations, ClickHouse, simulator, Arduino firmware, serial bridge, device APIs, telemetry ingestion, incidents, agent tools, new LangGraph workflows, command execution, approval UI, or DeviceHub frontend pages.

## 7. Future phases (reference only, not authorized)

Summarized from [PROJECT_SCOPE](PROJECT_SCOPE.md). These are not permission to implement them now.

- **Phase 2 / S1 foundations for the first vertical slice:** Rust device service and the first device/simulator → MQTT → PostgreSQL flow, with a validated safe stop command and acknowledgment. Order depends on the hardware inventory.
- **Phase 3 / S1 and S2 telemetry depth:** ingestion reliability, deduplication, dead-letter handling, simulator, query APIs, and later ClickHouse comparison per ADR-0004.
- **Phase 4 / S1 robot integration:** firmware and host bridge, only after hardware details and bench safety are verified.
- **Phase 5 / S2 platform depth:** command lifecycle, idempotency, expiry, offline handling, config versions, historical telemetry.
- **Phase 6 / S2 data and analytics:** range queries, aggregations, PostgreSQL-versus-ClickHouse measurements.
- **Phase 7 / S3 intelligence:** deterministic incidents, one LangGraph investigation agent, scoped Rust API tools, reuse of existing RAG with citations, human approval, verification.
- **Phase 8 / S4 experience:** DeviceHub dashboard views added to the existing frontend.
- **Phases 9–10 / S5 hardening and delivery:** observability, security, failure testing, reproducible benchmarks, agent evaluations, CI/CD, demo documentation.

## 8. ClickHouse decision

Follow ADR-0004:

- PostgreSQL owns transactional DeviceHub data and the first telemetry vertical slice.
- PostgreSQL + pgvector remains the existing RAG storage and retrieval foundation.
- ClickHouse is intended for high-volume raw telemetry and rollups in the later S2 phase.
- The first slice must use PostgreSQL only, so a real Postgres-only baseline exists.
- Add ClickHouse only in the later phase and measure it against PostgreSQL on the same representative workload. Record ingestion throughput, query latency, storage, CPU, memory, dataset size, and test conditions.
- ClickHouse must never be the source of truth for safety or command decisions.
- Do not add ClickHouse dependencies, containers, schemas, or migrations in Phase 1.

## 9. Communication style

- Be explicit and concise. State what you inspected, intend to change, and actually changed.
- Do not claim an architecture, test, benchmark, or hardware component works without evidence.
- Ask only for information that blocks the current phase.
- Do not silently make product-scope decisions.
- Prefer a concrete trade-off over a list of speculative technologies.
- Finish the requested phase; do not autonomously continue into the next one.
