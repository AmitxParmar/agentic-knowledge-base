# conventions.md

## Purpose
The engineering handbook: folder structure, naming, approved libraries,
patterns, and testing/documentation expectations for this repo.

## Dependencies
`docs/architecture.html`, `PRD.md` — this file implements their decisions in
day-to-day rules.

## Scope
Style and structure rules only. Technology *choices* are justified in
`docs/adr/`, not here.

## Folder Structure Rules
- **Feature-first, not technology-first.** A feature folder holds everything
  that feature needs (routes, logic, types, tests). Do not create top-level
  `agents/`, `prompts/`, `chains/`, `services/`, or `utils/` folders — those
  are technology-first groupings and tend to become dumping grounds.
- Top level:
  ```
  apps/{web,api,worker}
  src/{research,retrieval,ingestion,auth,observability,shared}
  docs/ infra/ tests/
  ```
- `src/shared/` is for code used by 2+ feature modules only. If only one
  feature uses it, it belongs in that feature's folder.
- `auth/` exists as a placeholder module for MVP (see PRD Non-Goals on
  RBAC) — keep it isolated so it's easy to fill in later without touching
  other features.

## Naming Conventions

| Item | Convention | Example |
|---|---|---|
| Python files/modules | `snake_case` | `hybrid_search.py` |
| TypeScript/React files | `kebab-case` for files, `PascalCase` for components | `progress-stream.ts`, `ChatPanel.tsx` |
| Database tables | `snake_case`, plural | `research_runs` |
| Env vars | `SCREAMING_SNAKE_CASE`, prefixed by domain | `MODEL_GATEWAY_BASE_URL` |
| Progress stage event names | exact strings from `docs/ui/ux.md` | `"Searching documents..."` |

## Approved Libraries (MVP)

| Concern | Library |
|---|---|
| API gateway | FastAPI |
| Orchestration | LangGraph |
| Frontend | Next.js |
| Web styling / utility CSS | tailwindcss + @tailwindcss/postcss (dev, ADR-009) |
| Vector index | pgvector (Turbovec replaced) |
| Relational DB | PostgreSQL |
| Local model serving | LM Studio (OpenAI-compatible endpoint) |
| Embeddings | Cohere embed-v3 |
| Rerank | Cohere rerank-v3 |
| PDF parsing | Docling |
| Audio transcription | faster-whisper |
| Code repo parsing | tree-sitter + gitingest |
| Chunking | Chonkie |
| Observability/tracing | Langfuse |

Anything not on this list requires an ADR before it's added — see
`docs/adr/`.

## Architectural Patterns
- **Agent contract pattern**: every agent (now or future) is specified with
  explicit Inputs, Outputs, Tools, and Success Criteria in `docs/specs/`
  before it's built. No agent exists in code without a matching spec.
- **Citation-at-retrieval pattern**: a citation is attached to evidence the
  moment it's retrieved, not reconstructed from the final answer text.
- **Model Gateway pattern**: agent and retrieval code call a single internal
  interface for model inference, never a provider SDK directly. Swapping the
  backend (LM Studio → LiteLLM, etc.) must not require touching that calling
  code — see ADR-003.
- **Progress-event pattern**: long-running work (ingestion, a research run)
  emits named stage events over the existing WebSocket/REST channel. The
  vocabulary is fixed in `docs/ui/ux.md` — don't invent new stage strings ad
  hoc.

## Testing Expectations
- Each feature module (`research/`, `retrieval/`, `ingestion/`) owns its
  unit tests under `tests/`, mirroring the `src/` path.
- The retrieval pipeline (rewrite → hybrid search → rerank) needs an
  integration test that asserts citations survive the full path.
- Golden-dataset evaluation (RAGAS/DeepEval) is Phase 2 — don't build it
  into MVP test infra.

## Documentation Expectations
- Every new component gets a short Purpose/Dependencies/Scope header, same
  as this file.
- A new infrastructure dependency needs an ADR before merge.
- A new agent needs a spec in `docs/specs/` before merge.
- Keep docs current with the code they describe — update the doc in the
  same change that changes the behavior it documents.
