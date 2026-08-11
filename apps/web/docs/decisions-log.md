# Decisions Log — Research Workspace UI

## Purpose

Every significant decision made during Phase 1 planning, with the reasoning
that supports it. Read this when you need to understand *why* a choice was
made, not just *what* was chosen.

## Decision record

### D-001: Stack — Next.js App Router (not TanStack Start)

**Decision:** Keep Next.js 16 App Router as configured. Do not migrate to
TanStack Start.

**Reasoning:** The repo's `apps/web/package.json` specifies `"next": "16.2.0"`
with no TanStack packages installed anywhere. The `tanstack-start-best-practices`
skill targets TanStack Router + server functions + `beforeLoad` auth — none
of which exist or apply here. Migrating would require ripping out Next.js,
rewriting the routing layer, and adding many new dependencies (each needing
an ADR). That is a different project, not a Phase 1 UI pass. The
`vercel-react-best-practices` skill, by contrast, targets Next.js App Router
exactly as configured and was folded in where applicable.

**Rejected alternatives:**
- Migrate to TanStack Start (full rewrite, out of scope).
- Hybrid TanStack Start + Next.js (mutually exclusive routing paradigms).

---

### D-002: TanStack AI — Phase 2, not Phase 1

**Decision:** Introduce TanStack AI in Phase 2 with a new ADR. Phase 1 is a
thin UI consumer of the existing Python agent loop.

**Reasoning:** TanStack AI runs a **frontend agent loop** (`chat()`, tools,
interrupts). This project already has an agent loop — and it's deliberately
**not** in the frontend (see D-003). The MVP flow is single question → single
answer, which doesn't need a client-side agent runtime. TanStack AI earns its
place in Phase 2 when multi-turn conversations, resumable streams, and
approval interrupts actually ship. Adding it in Phase 1 would mean a new
dependency, a new ADR, and most of its capability sitting unused.

**Rejected alternatives:**
- Phase 1 as streaming/state foundation (overkill for single-turn MVP).
- Phase 1 lightweight subset only (partial adoption is messy to complete later).

---

### D-003: Backend owns the agent loop (not frontend)

**Decision:** FastAPI/LangGraph remains the "brain." The frontend renders the
backend's agent loop; it does not run one.

**Reasoning:** ADR-001 (LangGraph) and ADR-003 (Model Gateway) lock the agent
loop and all model calls to the backend. The retrieval pipeline, embeddings,
and citation-at-retrieval all live in Python. Sliding the agent into the
frontend would require reopening both ADRs and duplicating the retrieval
pipeline in TypeScript. The backend streams a fixed-vocabulary protocol over
an AG-UI SSE endpoint (`POST /api/research/chat`); the frontend's job is to
render that faithfully.

**Implication:** TanStack AI (Phase 2) manages the **user interaction** with
the agent (chat state, streaming UX, client tools, approval interrupts) —
not the agent's reasoning or retrieval.

---

### D-004: Visual direction — Minimalist / editorial

**Decision:** Muted neutrals, single blue accent, hairline dividers, generous
whitespace, no glassmorphism / bento grids / gradient text.

**Reasoning:** Best first impression for a knowledge tool; lowest
implementation risk; keeps focus on dense research text rather than visual
decoration. The other options (Brutalist = noisy for long text; Soft SaaS =
less differentiated; Dark-tech = harder to keep accessible at high text
density) were all worse fits for a reading-heavy research workspace.

---

### D-005: Typography — Geist Sans + JetBrains Mono via `next/font`

**Decision:** Keep the existing Geist wiring; add JetBrains Mono. Both loaded
locally via `next/font`.

**Reasoning:** Geist is already wired in `layout.tsx`. Both fonts are
self-hosted, giving zero CLS and zero runtime fetch — better than the
design-skill default (Inter/Manrope from Google Fonts), which would add a
network request and layout shift for no benefit. A system-sans-only stack
was rejected because it loses brand voice.

---

### D-006: Citation UX — Numbered refs → popover/panel

**Decision:** Render `[n]` superscript after claims; clicking opens a popover
(desktop) or bottom sheet (mobile) showing `source_ref` + relevance score +
copy `chunk_id`.

**Reasoning:** Meets `docs/ux.md` §Citation Display Requirement (a visible,
clickable reference the user can inspect). Inline-highlighted spans were
rejected because the MVP payload doesn't use `answer_span_*` char offsets.
A static footnote list was rejected as weaker traceability that doesn't meet
the "clickable reference" bar.

---

### D-007: Citation chunk text — deferred

**Decision:** Phase 1 popovers show `source_ref` + score only. Full chunk text
requires a new `GET /ingestion/chunks/{id}` endpoint (Phase 2).

**Reasoning:** The chunk text lives in Postgres but is not exposed by the
current payload. Adding the endpoint is a small, additive backend change but
it's still a backend change — and Phase 1 requires none. The popover degrades
gracefully ("full text unavailable") until the endpoint lands.

---

### D-008: Data layer — @tanstack/react-query + ADR-004

**Decision:** Add React Query for upload mutations, job-status polling,
WS-hydrated run caching, and refetch-on-navigation. Cover it with a 1-page
ADR-004.

**Reasoning:** React Query is the industry standard for React server-state.
The `features/research/api/` hooks map 1:1 to its primitives. Native
`fetch`+`useState` would work but duplicates the library's caching/poll
logic with more code and more edge cases. ADR-004 satisfies conventions.md
rule 6 (no new deps without an ADR).

---

### D-009: Mobile citation panel — Bottom sheet

**Decision:** On `<768px` screens, the citation panel is a **bottom sheet**
(~40% height, swipe-to-dismiss), not a full-screen overlay.

**Reasoning:** Citation content is small (source path, score, copy action).
A full-screen overlay would hide the answer the user is trying to trace,
breaking spatial continuity. A bottom sheet keeps answer context visible,
matches platform-native iOS/Android patterns, and mirrors how major AI apps
(ChatGPT, Perplexity, Claude) handle citation previews on mobile.

---

### D-010: Source-type selector — Segmented control

**Decision:** Segmented control (PDF | Repo | Audio in one row), not a native
`<select>` dropdown.

**Reasoning:** Exactly three options — a segmented control shows them all at
once (single tap, zero hidden state, fully scannable). A `<select>` would
hide two-thirds behind an extra interaction for no spatial saving (three
short labels fit at 360px width). Segmented controls match the editorial
aesthetic (Linear, Raycast, Notion) and Radix's `ToggleGroup` makes it
accessible out of the box.

---

### D-011: Theme — Light + dark functional in Phase 1

**Decision:** Both themes fully functional via `next-themes`, bundled into
ADR-004.

**Reasoning:** The dark-mode tokens are defined regardless (pure CSS, near-zero
cost), so leaving them dormant wastes the work. A research tool is a
long-session, focus-heavy product — the most common reason users bounce from
a "polished" tool is the lack of dark mode. `next-themes` is tiny, SSR-safe,
and handles system-preference detection + hydration guard in one provider.
Bundling it into ADR-004 (rather than a separate ADR) keeps the ADR count down.

---

### D-012: Routing — /research full, /library + /runs as empty states

**Decision:** Build `/research` fully; ship `/library` and `/runs` as routes
with "Connect list API to enable" empty-state placeholders.

**Reasoning:** The nav shell is final after Phase 1; populating the deferred
routes later is a data swap, not a redesign. Building only `/research` and
adding the shell later would mean rebuilding navigation twice. Empty states
are honest (no fake data) and set up the routes for Phase 2 activation.

---

### D-013: Stream events not in React Query

**Decision:** `use-research-chat` (TanStack AI over SSE) owns the stream;
`use-research-run` folds stage/citation events into transient local state.
Only the completed `run_id` is written into the React Query cache.

**Reasoning:** Progress stages are transient **events**, not server state —
they don't belong in a data cache. The completed run, however, is durable
server state that benefits from React Query's hydration and refetch
capabilities. This separation keeps the two concerns clean.

---

### D-014: Component composition — Compound components

**Decision:** No mega-cards. Use compound composition
(`<UploadComposer>` with `<Dropzone>`, `<FileMeta>`, `<StageTimeline>`,
`<Submit>` children).

**Reasoning:** Matches the user's explicit pattern rule #3 (no `<ProductCard/>`
monoliths; compose `<ProductImage/>` + `<ProductInfo/>`). Improves readability,
testability, and reuse. Each piece can vary independently without prop-drilling
through a single giant component.

---

### D-015: withAuth HOC (thin MVP seam)

**Decision:** Implement `withAuth` as a thin wrapper that reads
`useWorkspaceId()`. It's a no-op in MVP (the dev ID always resolves) but
exists as a seam for the future JWT swap.

**Reasoning:** Matches the user's explicit pattern rule #2 (no `if(!user)`
guards inline; wrap with an HOC). Keeping it thin means the RBAC swap later
is a one-file change to `useWorkspaceId`, not a refactor across every page.

---

### D-016: AG-UI protocol — adopted (supersedes original deferral)

**Original decision:** Phase 1 used the backend's existing custom WS schema
(`{type:"progress"}`/`{type:"answer"}`); AG-UI adoption was deferred.

**Superseding decision:** ADR-005 Phase 4 adopted TanStack AI with the AG-UI
protocol over a plain SSE endpoint (`POST /api/research/chat`). The backend
now emits standard AG-UI events (`RUN_STARTED`, `TEXT_MESSAGE_START`, `CUSTOM`
stage/citations, `TEXT_MESSAGE_CONTENT`, `RUN_FINISHED`). TanStack AI's
`useChat` consumes the stream via `fetchServerSentEvents`; custom events route
through `onCustomEvent`. This was verified end-to-end against live Neon
Postgres + Upstash Redis + Groq/Cohere.

The legacy `/api/research/ws` WebSocket endpoint is retained for `wscat`-style
manual testing but is no longer the product path.

---

### D-017: Styling approach — CSS modules (not Tailwind)

**Decision:** Use CSS custom properties + per-component CSS modules
(`.module.css`), not Tailwind utilities.

**Reasoning:** Tailwind CSS was **not installed** in this project (no
`tailwind.config`, no PostCSS config, no `tailwindcss` dependency). The
existing scaffold uses plain CSS modules (`app/page.module.css`). Adding
Tailwind would introduce `tailwindcss` + `@tailwindcss/postcss` + an ADR
update. CSS modules + the design tokens already defined in `globals.css`
deliver the same result with **zero new build dependencies** and one less
ADR. The `cn()` helper is a 5-line function, not a dependency.

**Consequence:** `design-system.md` §1 and §4 were updated to remove
Tailwind references. The shadcn/ui primitives originally planned are
replaced with hand-built CSS-module components styled from the same
tokens. No ADR-004 update needed for Tailwind.
