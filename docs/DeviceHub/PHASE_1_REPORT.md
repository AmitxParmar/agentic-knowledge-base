# PHASE 1 REPORT — S0 Foundations

| | |
|---|---|
| Phase | 1 / S0 Foundations |
| Date | 2026-11-16 |
| Branch | `feat/devicehub-phase-1-foundation` |
| Baseline commit | `bac1d1f69ceecce35dcfe3752916f89c644c32ef` (`docs: update implementation plan`) |
| Baseline tag | `agentic-knowledgebase-v1.0.0` (annotated, created on `bac1d1f`) |
| Status | Complete — awaiting approval before Phase 2 |

Scope executed: repository inspection, baseline protection, hardware inventory, contract review, documentation adaptation, prerequisite verification, and Knowledge Base regression checks. No DeviceHub implementation was started.

---

## 1. Repository map

| Area | Path | Role |
|---|---|---|
| Python API | `apps/api/` | FastAPI gateway, LangGraph Research Agent, arq worker |
| Python modules | `apps/api/src/{research,retrieval,ingestion,auth,observability,shared,eval}` | Feature-first modules |
| App factory | `apps/api/app/{main.py,settings.py,workers.py}` | Lifespan, settings, worker settings |
| Migrations | `apps/api/alembic/versions/` | 9 revisions, default `public` schema |
| Web | `apps/web/` | Next.js 16 UI: `app/{research,library,runs,usage}`, `features/research/*` |
| Docs site | `apps/docs/` | Next.js scaffold, port 3001 |
| Shared packages | `packages/{ui,eslint-config,typescript-config}` | `@repo/*` |
| Host docs | `docs/{PRD.md,adr/,specs/,conventions.md,...}` | Knowledge Base design authority |
| DeviceHub docs | `docs/DeviceHub/` | This design set |
| CI | `.github/workflows/ci.yml` | Python 3.13 (ruff/pyright/pytest), turbo lint/types, non-blocking eval |
| Container | `apps/api/Dockerfile` | API + worker + migrations in one image |
| Deploy | `apps/api/render.yaml` | Render web service; Neon Postgres, Upstash Redis external |
| Compose | — | **does not exist** |
| Rust / firmware | — | **does not exist** |

## 2. Git baseline

| Item | Result |
|---|---|
| Starting branch | `main`, in sync with `origin/main` (0/0) |
| Starting commit | `bac1d1f` |
| Tracked modifications at inspection | none |
| Untracked at inspection | `docs/DeviceHub/` (22 files) and `docs/DeviceHub AI — Architecture.html` |
| Existing tags | none |
| Action taken | Tagged `bac1d1f`, branched, then committed the untracked DeviceHub docs unchanged as `eea8187` |
| Push / merge | not performed |

The tag deliberately points at `bac1d1f`, so the V1 baseline contains no DeviceHub material.

## 3. Hardware inventory

Full inventory: [HARDWARE_INVENTORY](HARDWARE_INVENTORY.md).

**No component has been inspected. No hardware claim is made.** Every row is `unknown` / `not inspected`.

Components awaiting identification: Arduino board, motor driver, ultrasonic sensor, line-following sensors, motors, chassis, power supply, USB/serial path, network module, physical e-stop, spares, datasheets.

Bench tests still required from you (none performed): board enumeration, sketch upload, ultrasonic plausibility, per-channel line sensing, single-wheel and dual-wheel motor drive with wheels lifted, battery under load, kill-switch cut, comms-loss stop, obstacle stop, e-stop latch.

Safety posture unchanged: motor control, thresholds, and the e-stop latch remain firmware responsibilities; the LLM never reaches pins; ADR-0008's serial bridge stays provisional.

## 4. Documentation changes

| File | Change | Why |
|---|---|---|
| `docs/DeviceHub/LLM_IMPLEMENTATION_GUIDE.md` | **Added** | The operating guide, with paths corrected to `docs/DeviceHub/` |
| `docs/DeviceHub/HARDWARE_INVENTORY.md` | **Added** | Inventory, unknowns, bench-test gates, blocked decisions |
| `docs/DeviceHub/REPOSITORY_INTEGRATION.md` | **Added** | Standalone layout → monorepo mapping; ports; env names; schema strategy |
| `docs/DeviceHub/PHASE_1_REPORT.md` | **Added** | This report |
| `docs/DeviceHub/adr/0013-devicehub-within-agentic-rag-monorepo.md` | **Added** | Records the host-repository adaptation as an accepted decision |
| `docs/DeviceHub/adr/README.md` | Added ADR-0013 row | Index consistency |
| `docs/DeviceHub/README.md` | Replaced the duplicated ADR index with a DeviceHub index | It was byte-identical to `adr/README.md` (no top-level index existed) |
| `docs/DeviceHub/SERVICE_BOUNDARIES.md` | §6 layout replaced with monorepo mapping | It mandated a standalone `devicehub/` tree |
| `docs/DeviceHub/LOCAL_DEVELOPMENT.md` | Current vs planned split; real prerequisites; Compose marked planned; Grafana moved 3001→3003; migration ownership; `.env.example` gap noted | It described a repository that does not exist |
| `docs/DeviceHub/{PRD,PROJECT_SCOPE,SECURITY,EVENT_CONTRACTS,SERVICE_BOUNDARIES}.md` | 9 broken `docs/adr/...` links corrected to `adr/...`; PRD links the inventory | Links resolved to `docs/DeviceHub/docs/adr/...` |
| `AGENTS.md` (root) | Appended DeviceHub section | Requested; additive only, existing content untouched |
| `README.md` (root) | 3-line note that DeviceHub is an extension | Explains the second product without disturbing the KB entry point |

No existing Knowledge Base document was edited, moved, or deleted.

## 5. Contract review

Reviewed `DATA_MODEL.md`, `EVENT_CONTRACTS.md`, `WORKFLOWS.md`, `SERVICE_BOUNDARIES.md`, and ADRs 0003–0010. Consistent: tenant never in topics, QoS/retained/ACL matrix, outbox + idempotency + expiry + boot binding, at-least-once with `(device_id, boot_id, seq)` dedupe, shed-oldest-telemetry policy, ClickHouse non-authoritative.

Unresolved inconsistencies, recorded not changed:

| ID | Finding | Where | Needs |
|---|---|---|---|
| C1 | `event` uses "its own counter per topic", but dedupe and ordering key on `(device_id, boot_id, seq)`. Two counters can collide under one key. | `EVENT_CONTRACTS.md` §3, §6; ADR-0006 | Decision: separate key namespace per topic, or a single seq space |
| C2 | Version policy says ingest supports `N` and `N−1`, while validation dead-letters unknown `schema_version`. `N−1` handling is undefined. | `EVENT_CONTRACTS.md` §4, §12 | Clarify supported-version window and dead-letter reason |
| C3 | "Common envelope" lists `device_id`/`seq`/`ts_mono_ms`, but `status`, `cfg`, and Last Will omit them; identity depends entirely on the topic. | `EVENT_CONTRACTS.md` §3, §5, §8 | Decide whether these payloads carry identity or rely on topic binding |
| C4 | Device `rejected` maps to terminal status, but the workflow shows `sent → failed` on device rejection, and the schema allows both `failed` and `rejected`. | `EVENT_CONTRACTS.md` §7.3; `WORKFLOWS.md` §3.1; `DATA_MODEL.md` §2 | Single mapping table for ack status → command status |
| C5 | The first slice is PostgreSQL-only, but the data model defines no PostgreSQL history table — history is ClickHouse-only. The Postgres baseline therefore has no defined history store. | ADR-0004; `DATA_MODEL.md` §6 | Define a Postgres history path for S1, or scope S1 to latest-state only |
| C6 | `boot_id` is "new on every device (or bridge) boot", so `target_boot_id` semantics differ when the bridge restarts but the MCU does not. | `EVENT_CONTRACTS.md` §3, §7.2 | Decide boot identity owner |

Additional integration findings, recorded in [REPOSITORY_INTEGRATION](REPOSITORY_INTEGRATION.md) §4:

| ID | Finding |
|---|---|
| I1 | `docs.*` is assigned to Python, but the existing corpus already lives in `public.documents` / `public.chunks`. Duplicating would fork RAG. |
| I2 | `DATA_MODEL` declares `vector(1536)`; the existing Cohere `embed-v3` corpus is **1024** dimensions. |
| I3 | LangGraph checkpoints are declared as `agent.*`; the existing implementation uses `public.langgraph_checkpoints`. |

## 6. Host project gaps (recorded, not fixed)

These are pre-existing issues in the Knowledge Base, found while verifying the baseline. They are **not** caused by DeviceHub and were not fixed in Phase 1.

| # | Gap | Evidence |
|---|---|---|
| H1 | Root `pnpm lint` fails because `apps/api`'s `lint` script calls bare `ruff`, which is only in the uv venv | `pnpm lint` → `api:lint: ruff: command not found` |
| H2 | `ruff check .` reports 6 errors in stray root scripts (`crash_probe.py`, `db_probe.py`, `scratch_test.py`) | `uv run ruff check .` |
| H3 | `basedpyright` reports 4 errors (chunker overlap typing, 3 test typing errors) | `uv run basedpyright` |
| H4 | `apps/api/SETUP.md` references `.env.example`, which does not exist; also references a non-existent `apps/worker/` | `find . -name .env.example` → none |
| H5 | `AGENTS.md` documents `arq apps.worker.main.WorkerSettings`; the real target is `app.workers.WorkerSettings` | `app/workers.py:9`, `apps/api/package.json` |
| H6 | No Docker Compose; PostgreSQL and Redis are managed services, not local containers | `render.yaml`, no compose file |
| H7 | The `understand-anything` knowledge graph is stale: analyzed at `1e117ad`, HEAD is `bac1d1f`, 133 committed file diffs | graph metadata vs `git diff` |

## 7. Local prerequisites (verified)

| Tool | Result |
|---|---|
| git 2.55.0 | ✅ |
| Node v26.7.0 / pnpm 9.0.0 | ✅ |
| uv 0.13.1 | ✅ |
| Python | system 3.14.7 (outside `>=3.11,<3.14`); `apps/api/.venv` is 3.13 ✅ |
| cargo/rustc 1.98.0, rustup 1.29.0 | ✅ (no Rust code yet) |
| Docker 29.7.2, Compose v5.5.1 | ✅ |
| arduino-cli | ✅ present, board unknown |
| `just` | ❌ missing |
| `sqlx-cli` | ❌ missing |
| `mosquitto_pub/sub` | ❌ missing |
| Local 5432 / 6379 / 1883 | ❌ nothing listening |
| `.env.example` | ❌ missing |

## 8. Knowledge Base baseline checks (actually run)

| Check | Command | Result |
|---|---|---|
| Python tests | `uv run pytest -q` | ✅ **311 passed, 1 skipped** (59.37 s) |
| Ruff | `uv run ruff check .` | ❌ 6 errors — pre-existing (H2) |
| Type check | `uv run basedpyright` | ❌ 4 errors — pre-existing (H3) |
| TS lint (web, docs, ui) | `pnpm --filter <pkg> lint` | ✅ all pass |
| TS type check | `pnpm check-types` | ✅ 3/3 tasks pass |
| Root lint | `pnpm lint` | ❌ fails at `api:lint` (H1) |

No test result is reported as passing unless it ran. The ruff/pyright/root-lint failures are baseline debt on `bac1d1f`, unchanged by this phase.

## 9. Decisions deferred to Phase 2

1. Hardware identification and the resulting pin/wiring plan (`[HW-TBD]`).
2. Whether the bridge is required, or an on-board network module replaces it (ADR-0008 revisit).
3. C1–C6 contract resolutions, before any ingest consumer or migration.
4. I1–I3 schema decisions: reuse `public.*` vs new `docs.*`/`agent.*`; embedding dimension 1024 vs 1536; checkpointer table.
5. The PostgreSQL history strategy for S1 (C5).
6. Compose topology, `just` task runner, and `sqlx-cli` adoption.
7. Mosquitto deployment shape and credential-sync mechanism (ADR-0003).
8. Whether to add a committed `.env.example` and fix H1–H5 as a separate, non-DeviceHub change.
9. Authentication for the DeviceHub API: local accounts vs external identity provider.
10. Port reassignment for observability tooling (Grafana 3003).

## 10. Preservation confirmation

- The existing Knowledge Base code was not modified: no changes under `apps/`, `packages/`, `.github/`, or existing `docs/` files.
- No existing migration was altered; no database command was run.
- No existing route, component, agent, prompt, retrieval path, or deployment file was changed.
- The only files touched are DeviceHub documents (`docs/DeviceHub/`), the root `AGENTS.md` (append-only), and the root `README.md` (three added lines).
- `apps/api/.env` remains untracked and git-ignored; no secret was read into a document or log.
- Nothing was pushed, merged, or deployed.

## 11. Acceptance checklist

| Criterion | Status |
|---|---|
| Knowledge Base intact | ✅ |
| Work isolated on `feat/devicehub-phase-1-foundation` | ✅ |
| Baseline tag created without overwriting | ✅ (none existed) |
| Hardware inventoried or explicitly unknown | ✅ |
| No unsafe hardware action | ✅ (none attempted) |
| Contracts and ADRs reviewed for consistency | ✅ (C1–C6 recorded) |
| Setup instructions reflect the real monorepo | ✅ |
| Existing checks run and reported honestly | ✅ (3 pre-existing failures reported) |
| No Phase 2 implementation started | ✅ |

**Phase 1 ends here. Phase 2 requires explicit authorization.**
