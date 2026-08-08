# Phasing — Phase 1 Execution Order

## Purpose

The week-by-week execution order for Phase 1. README.md defines *what* is
built; this doc defines *in what order* to build it so that every commit
ships something coherent.

## Dependencies

- `apps/web/docs/README.md` — file map and API contract
- `apps/web/docs/design-system.md` — tokens and typography

## Scope

Sequencing only. File contents are defined in README.md.

---

## Current state (what we're replacing)

`apps/web/app/page.tsx` is a single **351-line file with 8 useState hooks**.
It works as a harness but:
- No router — ingestion, ask, and answer all live on `/`.
- Citation display is a flat list with no chunk text, no popover.
- Progress is a disconnected pill row, not a stage timeline.
- The three view concerns (upload, ask, answer) are tightly coupled in one component.

Phase 1 replaces this with a routed, feature-foldered, designed workspace.

---

## Phase 1 execution order

### Week 1 — Design system + app shell + ingestion

**Goal:** the app looks like a product and the upload→poll loop works.

| Order | Deliverable | Files |
|---|---|---|
| 1 | Design tokens (CSS vars, light + dark) | `app/globals.css` |
| 2 | Fonts: add JetBrains Mono via `next/font` | `app/layout.tsx` |
| 3 | `lib/utils.ts` (cn helper) + `lib/env.ts` (env validation) | `lib/*` |
| 4 | `components/ui/*` shadcn primitives (button, input, textarea, skeleton, separator, tooltip, scroll-area, hover-card, toggle-group, sonner) | `components/ui/*` |
| 5 | `components/providers.tsx` (QueryClientProvider + ThemeProvider) | `components/providers.tsx` |
| 6 | `components/site-header.tsx` + `nav-link.tsx` | `components/*` |
| 7 | Route skeleton: `app/research/page.tsx`, `app/library/page.tsx`, `app/runs/page.tsx` (empty states) | `app/*` |
| 8 | `app/loading.tsx`, `app/error.tsx`, `app/not-found.tsx` | `app/*` |
| 9 | `features/research/api/query-client.ts` (retry:1, staleTime:5s) | `features/research/api/*` |
| 10 | `features/research/research-service.ts` (fetch wrapper + workspace header) | `features/research/*` |
| 11 | `features/research/api/use-upload.ts` (mutation) | `features/research/api/*` |
| 12 | `features/research/api/use-job-status.ts` (3s polling, stop on done|failed) | `features/research/api/*` |
| 13 | `features/research/components/upload-composer.tsx` + compound children | `features/research/components/*` |
| 14 | `features/research/components/progress-stage-list.tsx` + `stage-pill.tsx` | `features/research/components/*` |

**Week 1 exit:** upload a file, watch ingestion stages progress through
the 4-step timeline, see the document appear in the sidebar. `pnpm build`
passes.

### Week 2 — Research loop + citations + accessibility

**Goal:** the full ask→answer→citation loop works and passes a11y checks.

| Order | Deliverable | Files |
|---|---|---|
| 15 | `features/research/hooks/use-research-ws.ts` (lifecycle guards, safe JSON, abort) | `features/research/hooks/*` |
| 16 | `features/research/hooks/use-workspace-id.ts` (MVP seam) | `features/research/hooks/*` |
| 17 | `features/research/hooks/use-auto-scroll.ts` | `features/research/hooks/*` |
| 18 | `features/research/utils/ws-adapter.ts` (typed event parsing) | `features/research/utils/*` |
| 19 | `features/research/utils/parse-citations.ts` (group by document+chunk) | `features/research/utils/*` |
| 20 | `features/research/api/use-research-run.ts` (WS lifecycle → stages[], answer, error) | `features/research/api/*` |
| 21 | `features/research/api/use-run-detail.ts` (GET /runs/{id} hydration) | `features/research/api/*` |
| 22 | `features/research/components/question-composer.tsx` | `features/research/components/*` |
| 23 | `features/research/components/citation-ref.tsx` (`[n]` button + hover popover) | `features/research/components/*` |
| 25 | `features/research/components/citation-panel.tsx` (side sheet / bottom sheet) | `features/research/components/*` |
| 26 | `features/research/components/research-workspace.tsx` (layout shell) | `features/research/components/*` |
| 27 | `features/research/components/empty-state.tsx` (reusable) | `features/research/components/*` |
| 28 | Accessibility pass: focus trap in sheets, reduced-motion, aria-live, keyboard order | all components |
| 29 | `pnpm build` + `pnpm check-types` + `turbo lint` all green | repo root |

**Week 2 exit:** full core loop works end-to-end against a running backend.
Upload → poll → ask → cited answer → citation popover/panel. Keyboard +
screen-reader pass complete.

---

## Hook behavior specifics

### `useUpload`
- TanStack `useMutation` → `POST /api/ingestion/upload` (multipart FormData).
- `onSuccess`: extracts `job_id` from response, starts a dependent
  `useJobStatus` query.

### `useJobStatus(jobId)`
- TanStack `useQuery` → `GET /api/ingestion/jobs/{id}`.
- `refetchInterval: 3000` (3 seconds).
- `enabled: !!jobId` — only runs when a job exists.
- Stops polling when `stage === 'done' || stage === 'failed'`
  (set `refetchInterval: false` in that case).

### `useResearchRun`
- Opens a WebSocket to `WS_BASE_URL/api/research/ws`.
- Sends `{ question }` on `onopen`.
- Accumulates `{type:"progress"}` events into a local `stages[]` array
  (NOT React Query — stages are transient events, not server state).
- On `{type:"answer"}`: stores `text`, `citations`, and `run_id` in the
  React Query cache under the `['run', run_id]` key so `useRunDetail`
  can hydrate on navigation/back without re-running.
- On `{type:"error"}`: surfaces error message, sets idle.
- Exposes: `{ status, stages[], answer, citations, error, startRun, abort }`.

### `useRunDetail(runId)`
- TanStack `useQuery` → `GET /api/research/runs/{id}`.
- `enabled: !!runId`.
- Initial data is seeded from `useResearchRun`'s cache write when the WS
  answer arrives (no extra network call on first render after a run).

### Query client defaults
```ts
new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 5_000, refetchOnWindowFocus: false },
  },
})
```

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
dynamic origin (e.g. Render preview URLs), either rebuild on deploy or
proxy the API through a same-origin `/api` route in Next.js.

---

## Package list (exact)

These are the shadcn/ui primitives to generate (via `turbo gen` or manual
scaffold). All are unstyled primitives configured with the design tokens
above:

1. `button` — primary / secondary / ghost / destructive variants
2. `input` — text input with focus ring
3. `textarea` — multiline for question composer
4. `dialog` — modal base (used by citation panel on desktop)
5. `dropdown-menu` — source-type selector (if not using toggle-group)
6. `skeleton` — loading states
7. `separator` — hairline dividers between sections
8. `tooltip` — hover labels
9. `scroll-area` — independent scroll regions (sidebar, answer column)
10. `hover-card` — citation popover on desktop
11. `toggle-group` — source-type segmented control (PDF | Repo | Audio)
12. `sonner` — toast notifications (upload complete, errors)
13. `label` — visible form labels
14. `card` — optional primitive wrapper

Plus non-shadcn additions:
- `@tanstack/react-query`
- `next-themes`
- `lucide-react`
- `clsx` + `tailwind-merge`

---

## Definition of done

Same as README.md — repeated here for the phasing context:

1. `pnpm build` + `pnpm check-types` pass.
2. `turbo lint` clean.
3. Core loop works end-to-end against a running backend.
4. Keyboard + screen-reader pass on the loop.
5. ADR-004 merged into `docs/adr/` and conventions.md updated.
