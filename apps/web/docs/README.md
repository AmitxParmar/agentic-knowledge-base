# Research Workspace UI — Phase 1 Master Spec

## Purpose

Build the MVP research workspace UI as a **well-designed consumer** of the
existing Python agent loop (FastAPI + LangGraph). The backend is complete;
this phase delivers the frontend that makes "upload → ask → cited answer"
feel trustworthy, legible under load, and faithful to the locked UX
vocabulary in `docs/ux.md`.

## Dependencies

- `docs/PRD.md` — MVP scope (F1–F8, Non-Goals)
- `docs/ux.md` — frozen progress-stage vocabulary + citation-display requirement
- `docs/conventions.md` — feature-first structure, approved libraries, naming
- `docs/specs/researcher.md` — Research Agent contract
- `docs/specs/ingestion.md` — Ingestion pipeline stages
- `docs/adr/` — locked technology choices (ADR-001 LangGraph, ADR-002 Turbovec, ADR-003 Model Gateway)
- `apps/api/src/shared/progress.py` — the only valid stage strings

## Scope

Single research page (`/research`) covering the full core loop, plus
placeholder routes (`/library`, `/runs`). **No backend changes required.**

For the execution order (week 1 / week 2) and detailed hook behavior, see
[`phasing.md`](./phasing.md).

## Context

The backend is functionally complete for the MVP core loop:
- `POST /api/ingestion/upload` (multipart, async via arq)
- `GET /api/ingestion/jobs/{job_id}` (polls a `JobStage` enum)
- `WS /api/research/ws` (streams the fixed four-stage vocabulary, then
  `{type:"answer"}` with citations)
- `GET /api/research/runs/{run_id}` (fetch a completed run)

Auth is a dev stub — every request is silently scoped to
`workspace_id = 00000000-0000-0000-0000-000000000001`.

The current frontend at `apps/web/app/page.tsx` is a single **351-line
file with 8 useState hooks**. It works as a core-flow harness, but:
- No router — ingestion, ask, and answer all live on `/`.
- Citation display is a flat list with no popover, no chunk text.
- Progress is a disconnected pill row, not a stage timeline.
- The three view concerns are tightly coupled in one component.

The PRD's four MVP goals (F1→F8) are exercised but not designed. Phase 1
replaces this harness with a deliberately-designed research workspace that
makes "upload → ask → cited answer" feel trustworthy, legible under load,
and immediately confirms the UX rule that citations must always be
traceable.

**Authority:** `PRD.md` MVP goals F1–F8 & Non-Goals, `docs/ux.md` progress
vocabulary + citation-display requirement (the fixed stage strings in
`src/shared/progress.py` are the only ones the client may render — we add
none), `docs/conventions.md` feature-first structure.

---

## Locked decisions

| # | Decision | Value |
|---|---|---|
| 1 | Stack | **Next.js 16 App Router** (installed). TanStack Start skill NOT applied — wrong stack. |
| 2 | TanStack AI | **Phase 2** only (new ADR then). Phase 1 is a thin UI consumer of the Python agent loop. |
| 3 | Visual direction | **Minimalist / editorial** — muted neutrals, single accent, hairline dividers, generous whitespace. |
| 4 | Typography | **Geist Sans + JetBrains Mono** via `next/font` (local, zero CLS, no Google Fonts). |
| 5 | Citation UX | **Numbered `[n]` refs → popover/panel** showing `source_ref` + relevance score. Chunk text deferred. |
| 6 | Data layer | **`@tanstack/react-query`** + a **1-page ADR-004** for conventions.md compliance. |
| 7 | Routing | **`/research`** (full build) + **`/library`** / **`/runs`** (empty-state placeholders). |
| 8 | Backend changes | **None required** in Phase 1. Optional `GET /ingestion/chunks/{id}` deferred. |
| 9 | Mobile citation panel | **Bottom sheet** on `<768px` (preserves answer context, platform-native). |
| 10 | Source-type selector | **Segmented control** (PDF | Repo | Audio) — 3 options, all visible, single tap. |
| 11 | Theme | **Light + dark functional** via `next-themes`, bundled into ADR-004. |

---

## API contract (all endpoints exist today)

```
POST   /api/ingestion/upload        multipart(file, source_type) → {document_id, job_id, status}
GET    /api/ingestion/jobs/{id}     → {stage, error?}
WS     /api/research/ws             {question} → progress* → answer → done|error
GET    /api/research/runs/{id}      → {run_id, question, answer, status, citations[], created_at}
GET    /health                      → {status:"ok"}
```

Workspace scoping: optional `X-Workspace-Id` header; omit → dev workspace.

### WebSocket message schema

```
client → server:  { "question": "..." }
server → client:  { "type": "progress", "stage": "<one of 4 fixed strings>" }
server → client:  { "type": "answer", "run_id", "text", "citations": [{chunk_id, source_ref, relevance_score}] }
server → client:  { "type": "done" }
server → client:  { "type": "error", "message" }
```

The four fixed stage strings (frozen in `apps/api/src/shared/progress.py`):
`Searching documents...` → `Reviewing evidence...` → `Generating report...` → `Finalizing answer...`

---

## New dependencies

| Package | Purpose | Conventions compliance |
|---|---|---|
| `@tanstack/react-query` ^5 | Server-state: mutations, polling, caching, refetch | Covered by ADR-004 |
| `next-themes` ^0.4 | System-preference dark mode + manual override + SSR guard | Bundled into ADR-004 |
| `lucide-react` ^0.400+ | SVG icon set (no emoji) | Bundled into ADR-004 |
| `clsx` ^2 + `tailwind-merge` ^2 | `cn()` class utility | Bundled into ADR-004 |

All added to `apps/web/package.json`.

---

## File-by-file deliverable

```
apps/web/
├── app/
│   ├── layout.tsx                     MOD  top nav (research / library / runs) + Toaster + providers
│   ├── globals.css                    MOD  minimal editorial tokens + typography scale
│   ├── page.tsx                       MOD  redirect → /research (or thin landing)
│   ├── loading.tsx                    ADD  route-level skeleton
│   ├── error.tsx                      ADD  route-level error boundary
│   ├── not-found.tsx                  ADD  404
│   ├── page.module.css                DEL  replaced by Tailwind utilities + token classes
│   ├── research/
│   │   ├── page.tsx                   ADD  server entry → <ResearchWorkspace/>
│   │   └── layout.tsx                 ADD  sidebar + chat area + answer column shell
│   ├── library/
│   │   └── page.tsx                   ADD  empty-state placeholder
│   └── runs/
│       └── page.tsx                   ADD  empty-state placeholder
│
├── components/
│   ├── ui/                            ADD  shadcn primitives (button, input, textarea, dialog,
│   │                                         dropdown-menu, skeleton, separator, tooltip,
│   │                                         scroll-area, hover-card, toggle-group, sonner)
│   ├── providers.tsx                  ADD  QueryClientProvider + ThemeProvider wrapper
│   ├── error-boundary.tsx             ADD  class-component error boundary
│   ├── site-header.tsx                ADD  top nav with active-route highlight
│   └── nav-link.tsx                   ADD  active-state nav item
│
├── features/
│   └── research/
│       ├── api/
│       │   ├── query-client.ts             ADD  global QueryClient (retry:1, staleTime:5s)
│       │   ├── use-upload.ts               ADD  mutation → POST /upload; onSuccess start job polling
│       │   ├── use-job-status.ts           ADD  query polling GET /jobs/{id} (3s; stop on done|failed)
│       │   ├── use-research-run.ts         ADD  WS lifecycle → stages[], answer, error
│       │   └── use-run-detail.ts           ADD  query GET /runs/{id} for hydration/refetch
│       │
│       ├── hooks/
│       │   ├── use-research-ws.ts          ADD  raw WS wrapper (lifecycle guards, safe JSON, abort)
│       │   ├── use-workspace-id.ts          ADD  returns dev ID (MVP seam; JWT later)
│       │   └── use-auto-scroll.ts           ADD  scroll-to-bottom on stage updates
│       │
│       ├── components/
│       │   ├── research-workspace.tsx       ADD  layout shell (sidebar + chat + answer)
│       │   ├── upload-composer.tsx          ADD  file picker + source-type select + upload CTA
│       │   │   ├── upload-dropzone.tsx      ADD  (compound) drag/drop
│       │   │   ├── upload-file-meta.tsx     ADD  chosen file name/size/type
│       │   │   └── upload-stage-pill.tsx    ADD  live stage badge
│       │   ├── question-composer.tsx        ADD  textarea + char hint + submit
│       │   ├── progress-stage-list.tsx      ADD  fixed-vocabulary stage timeline
│       │   │   └── stage-pill.tsx           ADD  single stage (pending→active→complete)
│       │   ├── answer-panel.tsx             ADD  answer text + progressive citation attach
│       │   ├── citation-ref.tsx             ADD  superscript [n] button + hover popover
│       │   ├── citation-panel.tsx           ADD  side sheet: source_ref, score bar, copy chunk_id
│       │   └── empty-state.tsx              ADD  reusable empty state
│       │
│       ├── utils/
│       │   ├── parse-citations.ts           ADD  group citation[] by document+chunk for display order
│       │   └── ws-adapter.ts                ADD  parse WS messages into typed events
│       │
│       └── research-service.ts             ADD  fetch wrapper injecting workspace-id header
│
└── lib/
    ├── utils.ts                             ADD  cn() helper (clsx + tailwind-merge)
    └── env.ts                               ADD  NEXT_PUBLIC_API_BASE_URL / WS base URL + runtime validation
```

---

## Component composition patterns

### Compound components (no mega-cards)

```tsx
<UploadComposer onUpload={...}>
  <UploadComposer.Dropzone accept={...} />
  <UploadComposer.FileMeta file={file} />
  <UploadComposer.StageTimeline stage={job.stage} />
  <UploadComposer.Submit disabled={!file}>Start ingestion</UploadComposer.Submit>
</UploadComposer>
```

### withAuth HOC (thin MVP seam)

```tsx
export function withAuth<P extends object>(Component: React.ComponentType<P>) {
  return function Authenticated(props: P) {
    const workspaceId = useWorkspaceId();
    if (!workspaceId) return <RedirectToSignIn />; // never triggers in MVP
    return <Component {...props} workspaceId={workspaceId} />;
  };
}
```

### WebSocket ownership

`use-research-ws` owns transient stages via local state (not React Query —
stages are transient events, not server state). The completed `run_id` is
written into the React Query cache so `/runs/{id}` can hydrate on
navigation/back without re-running.

---

## Accessibility & UX rules

1. `role="log"` `aria-live="polite"` on stage list (screen readers announce stage changes).
2. Citation refs are real `<button>` elements, ≥44×44px, `aria-label="Citation n: <source_ref>"`.
3. Focus order: sidebar → composer → answer; focus trap in citation side sheet.
4. Color alone never indicates stage state — icon + text + color.
5. No emoji in UI — all icons SVG via `lucide-react`.
6. All text ≥ contrast 4.5:1 in both themes; body base 15px (never < 12px).
7. Raw hex banned from components — always `hsl(var(--token))`.
8. `prefers-reduced-motion` disables all animation.

---

## What Phase 1 explicitly does NOT do

- No TanStack AI (Phase 2, new ADR).
- No `GET /ingestion/chunks/{id}` endpoint (would let citations show full passage — deferred).
- No `/library` or `/runs` data (empty states only).
- No new agents (PRD Non-Goals).
- No changes to `apps/api` (backend already complete for MVP).
- No progress-vocabulary additions (frozen by `docs/ux.md` + `src/shared/progress.py`).

---

## Definition of done

1. `pnpm build` + `pnpm check-types` pass.
2. `turbo lint` clean.
3. Core loop works end-to-end against a running backend: upload → poll → ask → cited answer → citation popover.
4. Keyboard + screen-reader pass on the loop.
5. ADR-004 merged into `docs/adr/` and conventions.md Approved Libraries updated.

---

## Deployment / runtime

### Environment variables (`lib/env.ts`)

| Variable | Required | Default | Used for |
|---|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | yes | `http://localhost:8000` | REST calls (upload, job status, run detail) |
| `NEXT_PUBLIC_WS_BASE_URL` | no | derived from API base (`http`→`ws`, `https`→`wss`) | WebSocket connection |

Runtime validation at boot throws a clear error if the API base URL is
missing — fails fast instead of producing cryptic network errors.

### CORS

Backend (`apps/api/app/main.py`) already configures CORS via
`settings.cors_origin_list`. Dev origin is `localhost:3000`. No frontend
change needed; ensure the deployed origin is in `CORS_ORIGIN_LIST` when
going to prod.

### Build vs runtime

`NEXT_PUBLIC_*` vars are inlined at build time (Next.js requirement). For
dynamic origins (e.g. Render preview URLs), either rebuild on deploy or
proxy the API through a same-origin `/api` route in Next.js.

---

## Related docs

- [`design-system.md`](./design-system.md) — tokens, typography, layout, motion
- [`adr-tanstack-react-query.md`](./adr-tanstack-react-query.md) — ADR-004 (data layer + theming)
- [`phase-2.md`](./phase-2.md) — deferred scope
- [`decisions-log.md`](./decisions-log.md) — every decision + reasoning
- [`phasing.md`](./phasing.md) — week-by-week execution order, hook behavior specifics, package list
