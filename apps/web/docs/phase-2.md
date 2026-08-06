# Phase 2 — Deferred Scope

## Purpose

Everything explicitly deferred from Phase 1, captured here so Phase 1 stays
focused and bounded. Each item is a candidate for a future ADR + spec.

## Dependencies

- `apps/web/docs/README.md` — Phase 1 master spec
- `docs/PRD.md` → Non-Goals (deferred Planner, Critic, memory, MCP, RBAC)

## Scope

Phase 2 is not yet planned in detail. This doc records *what* is deferred,
not *how* it will be built.

---

## 1. TanStack AI (frontend agent runtime)

**What:** A headless agent loop in TypeScript — `chat()`, isomorphic tools
via `toolDefinition().server()/.client()`, `(state) => boolean` stop
strategies, `needsApproval` interrupts, AG-UI event streams.

**Where it fits:** the frontend runtime for AI interaction. It manages the
**user interaction with the agent** (chat state, streaming, client tools,
approval interrupts, persistence), while **FastAPI/LangGraph remains the
brain** (orchestration, retrieval, planning, embeddings, LLM calls).

**Where it does NOT fit (keep in backend):**
- Agent orchestration (LangGraph)
- RAG pipeline / retrieval / embeddings
- LLM calls (Model Gateway, ADR-003)
- MCP (handled by Python backend)

**Capabilities unlocked:**
- Multi-turn conversations (follow-ups, clarifications).
- Resumable streams (refresh mid-run, pick up where left off).
- Client-side tools: clipboard (copy citations), notifications
  (ingestion done), file picker.
- Human approval interrupts: "Delete workspace?", "Run expensive research?".
- Conversation persistence (save/resume threads).
- AG-UI protocol (standard event stream between backend and frontend).

**Prerequisites:**
- A new ADR (ADR-005?) reopening the question of client-side agent loops.
  ADR-001 (LangGraph) and ADR-003 (Model Gateway) currently own the agent
  loop and model calls — they are not violated (the backend stays the
  brain), but the client-side runtime needs its own justification.
- A new spec in `docs/specs/` defining the client-side agent's inputs,
  outputs, tools, and success criteria (per conventions.md → Agent
  contract pattern).
- Backend work to support AG-UI or a custom→AG-UI adapter (the current WS
  schema is `{type:"progress"}/{type:"answer"}`, not AG-UI).

**Decision:** Phase 1 is a thin UI consumer of the existing agent loop.
TanStack AI enters in Phase 2 with a new ADR.

---

## 2. Citation full-text (chunk content in popover)

**What:** Show the actual chunk passage (not just `source_ref` + relevance)
inside the citation popover/panel.

**Why deferred:** The chunk text lives in Postgres (`chunks.text`) but is
**not exposed** by the current `GET /api/research/runs/{id}` payload.
Citations arrive as `{chunk_id, source_ref, relevance_score}` only.

**Prerequisite backend work:**
- New read-only endpoint: `GET /api/ingestion/chunks/{chunk_id}` →
  `{chunk_id, text, source_ref}`.
- Added to `apps/api/src/ingestion/router.py`.
- Returns the `text` column from the `chunks` row.

**Frontend change:** `citation-panel.tsx` fetches chunk text by `chunk_id`
and renders it; falls back to "full text unavailable" if the endpoint is
absent (graceful degradation for Phase 1 popovers).

---

## 3. Library route (`/library`)

**What:** List, manage, and delete uploaded documents.

**Why deferred:** Phase 1 ships `/library` with an empty-state placeholder.
Populating it requires backend list endpoints that don't exist yet.

**Prerequisite backend work:**
- `GET /api/ingestion/documents` → list documents (paginated, workspace-scoped).
- `DELETE /api/ingestion/documents/{id}` → delete a document + its chunks + vectors.

**Frontend change:** `use-documents.ts` (already stubbed in the file map)
becomes active; `library/page.tsx` renders the list.

---

## 4. Runs route (`/runs`)

**What:** Browse past research runs, click to hydrate a completed run.

**Why deferred:** Phase 1 ships `/runs` with an empty-state placeholder.

**Prerequisite backend work:**
- `GET /api/research/runs` → list runs (paginated, workspace-scoped).

**Frontend change:** `use-run-history.ts` becomes active; `runs/page.tsx`
renders the list. Clicking a run navigates to `/runs/{id}` which calls
`GET /api/research/runs/{id}` (this endpoint **already exists**) to hydrate.

---

## 5. Syntax highlighting for code citations

**What:** When a citation's `source_ref` points to a repo file, render the
chunk text with syntax highlighting instead of plain monospace.

**Why deferred:** Depends on chunk text being available (deferred item #2).
Without text to highlight, there's nothing to render.

**Frontend change:** Add a lightweight highlighter (e.g. `prism-react-renderer`)
to `citation-panel.tsx` when the source type is `repo`.

---

## 6. Client-side tools & approval interrupts (Phase 2 UX)

**What:** Using TanStack AI's client-side tool capabilities:
- Clipboard: copy a citation's `chunk_id` or source_ref.
- Notifications: "Ingestion complete" / "Research run failed".
- Approval: "Run research on this question?" before opening the WS.

**Why deferred:** Requires TanStack AI (deferred item #1).

---

## Phase 2 execution order (tentative)

1. **ADR-005** — TanStack AI client-side runtime.
2. **ADR-006** — AG-UI protocol (if adopted) or document the decision to
   keep the custom WS schema.
3. **Backend:** `GET /ingestion/chunks/{id}`, `GET /ingestion/documents`,
   `DELETE /ingestion/documents/{id}`, `GET /research/runs`.
4. **Frontend:** activate deferred hooks/routes, add citation text,
   syntax highlighting, approval interrupts.

This order is subject to a Phase 2 planning pass — not yet committed.
