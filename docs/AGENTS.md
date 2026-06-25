# AGENTS.md

## Purpose
Rules for any AI coding agent (Claude Code, Codex, Cursor, Gemini, OpenHands,
etc.) working in this repository.

## Dependencies
`PRD.md`, `docs/adr/`, `docs/specs/`, `conventions.md` — all required reading
below.

## Scope
Process and decision-authority rules. Not a style guide — that's
`conventions.md`.

## Required Reading Order
Before writing or editing any code, read in this order:
1. `PRD.md` — what's in scope, what's explicitly deferred
2. `docs/adr/` — accepted technology decisions and why
3. The relevant file in `docs/specs/` for the component you're touching
4. The existing code in that area of the repo

Do not skip to step 4. Specs and ADRs exist so you don't have to re-derive
decisions that are already made.

## Decision Authority (highest wins)
1. `docs/architecture.html` — overall system design
2. `PRD.md` — MVP scope boundary
3. ADRs — locked technology choices
4. Specs — component contracts
5. `conventions.md` — style and structure

If a request conflicts with a higher-authority document, flag the conflict
instead of silently picking one side.

## Rules
- Follow ADR decisions. Don't introduce a competing library or pattern an
  ADR already settled (e.g., don't add pgvector — see ADR-002).
- Follow `conventions.md` for folder structure and naming without exception.
- Prefer modifying an existing file over creating a new one.
- Don't add a dependency that isn't already listed in `conventions.md` →
  Approved Libraries without first proposing an ADR.
- Keep solutions as simple as the spec requires. No speculative
  abstractions for inputs the spec doesn't define.
- Do not add a new agent (Planner, Critic, or anything else) without a new
  spec file under `docs/specs/` justifying it against `PRD.md` → Non-Goals.
- Every retrieval result the Research Agent uses must carry a citation
  reference through to the final answer — never drop the chunk/document
  link partway through a change.
- Never surface chain-of-thought, internal reasoning, or raw prompts to the
  client. Only the progress-stage vocabulary in `docs/ui/ux.md` is allowed
  on that channel.

## Definition of Done for a Change
- Matches the relevant spec's stated inputs/outputs/tools/success criteria
- Doesn't reintroduce anything listed in `PRD.md` → Non-Goals
- Follows `conventions.md` structure and naming
- Citations remain intact end-to-end if the change touches retrieval or the
  Research Agent
