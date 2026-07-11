# AGENTS.md

## Monorepo layout

This is a **pnpm + Turborepo** monorepo with a **mixed Python/TypeScript** stack.

| Path | Runtime | Role |
|---|---|---|
| `apps/api/` | Python 3.11+ (uv, FastAPI) | API gateway, LangGraph agents, arq workers |
| `apps/web/` | TypeScript (Next.js 16, React 19) | Frontend, port 3000 |
| `apps/docs/` | TypeScript (Next.js 16, React 19) | Docs site, port 3001 |
| `packages/ui/` | TypeScript (`@repo/ui`) | Shared React components |
| `packages/eslint-config/` | TypeScript (`@repo/eslint-config`) | Shared ESLint config |
| `packages/typescript-config/` | TypeScript (`@repo/typescript-config`) | Shared tsconfig |
| `apps/api/src/` | Python | Feature modules: research, retrieval, ingestion, auth, observability, shared |
| `apps/api/app/` | Python | FastAPI app factory, settings, workers |
| `docs/` | Markdown | PRD, ADRs, specs, conventions |

## Commands

```bash
# Monorepo-wide (run from repo root)
pnpm install                  # install all JS deps
pnpm build                    # turbo build all
pnpm lint                     # turbo lint all
pnpm check-types              # turbo typecheck all
pnpm format                   # prettier on **/*.{ts,tsx,md}

# Filter to one app/package
turbo build --filter=web
turbo lint --filter=@repo/ui
turbo check-types --filter=docs

# Python API (run from apps/api/)
uv run uvicorn app.main:app --reload --port 8000
uv run pytest                 # tests from apps/api/tests/
uv run ruff check .           # lint
uv run ruff format .          # format
uv run basedpyright           # typecheck
alembic upgrade head          # run migrations

# Async ingestion worker (run from apps/api/)
arq apps.worker.main.WorkerSettings
```

## Critical rules

1. **All `uv run` commands execute from `apps/api/`**, not the repo root. The `app` Python package and `pyproject.toml` live there.
2. **All model inference must go through `src/shared/model_gateway.py`**. Never import Groq, OpenAI, or any provider SDK directly in feature code. Fallback chain: Groq → OpenRouter. See ADR-003.
3. **Citations must survive the full retrieval pipeline.** Every claim in a Research Agent answer traces back to a retrieved chunk. Never drop citation references mid-pipeline.
4. **Never surface chain-of-thought or raw prompts to the client.** Only the progress-stage vocabulary from `docs/ux.md` is allowed on the frontend channel.
5. **No new agents without a spec.** Don't add Planner, Critic, or any new agent without a spec file under `docs/specs/` justified against `PRD.md` Non-Goals.
6. **No new dependencies without an ADR.** Anything not in `conventions.md` → Approved Libraries needs a proposal in `docs/adr/`.
7. **Feature-first folder structure.** No top-level `agents/`, `prompts/`, `services/`, or `utils/` directories. Feature modules live in `src/{research,retrieval,ingestion,auth,observability,shared}` within `apps/api/`.

## Decision authority (highest wins)

1. `docs/latest-architecture.html` — overall system design
2. `docs/PRD.md` — MVP scope boundary
3. `docs/adr/` — locked technology choices
4. `docs/specs/` — component contracts
5. `docs/conventions.md` — style and structure

## Required reading before writing code

1. `docs/PRD.md` — what's in scope, what's deferred
2. `docs/adr/` — accepted technology decisions
3. The relevant `docs/specs/` file for the component you're touching
4. The existing code in that area

## Python specifics

- **Ruff** config: `apps/api/ruff.toml`. Line length 100, target Python 3.11, rules E/F/I/UP/B/SIM/RUF. E501 and B008 ignored.
- **Typecheck**: basedpyright (config at `apps/api/pyrightconfig.json`).
- **Tests**: pytest with `asyncio_mode = "auto"`, testpaths `tests/`.
- **Pydantic HttpUrl pitfall**: Don't use `HttpUrl` for fields passed to OpenAI SDK clients — use `str` type directly. Pydantic's `HttpUrl` doesn't accept plain string defaults in `Field()`.
- **Settings**: `pydantic-settings` for env vars; API keys set in `apps/api/.env`.
- **Alembic**: when adding new ORM models, import them in `apps/api/alembic/env.py` so autogenerate discovers them. All models inherit from `src.shared.database.Base`.
- **Adding a feature**: build in `apps/api/src/<feature>/`, add router in `router.py`, uncomment the `include_router` line in `apps/api/app/main.py`, write tests in `apps/api/tests/<feature>/`.
- **Detailed setup**: see `apps/api/SETUP.md`.

## TypeScript specifics

- **Package manager**: pnpm 9+ (enforced via `packageManager` in root `package.json`).
- **React 19** and **Next.js 16** across all TS apps.
- **Shared packages**: `@repo/ui`, `@repo/eslint-config`, `@repo/typescript-config` — referenced via `workspace:*`.
- **Naming**: kebab-case files, PascalCase components.
- **Lint**: ESLint 9 flat config (`eslint.config.js` per app).
- **Typecheck**: `tsc --noEmit` (plus `next typegen` for Next.js apps).

## Naming conventions

| Item | Convention |
|---|---|
| Python files | `snake_case` |
| TS/React files | `kebab-case` (files), `PascalCase` (components) |
| DB tables | `snake_case`, plural |
| Env vars | `SCREAMING_SNAKE_CASE`, prefixed by domain |

## Infra prerequisites

- Python 3.11+, Node 20+, pnpm 9+
- PostgreSQL (async driver: asyncpg)
- Redis (for arq job queue) (we will use rediss://)
- Will use groq/openrouter free models (or) LM Studio or compatible OpenAI endpoint for local model serving
- BGE-M3 / BGE-Reranker-v2-m3 for embeddings and reranking

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
| ------ | ---------- |
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
