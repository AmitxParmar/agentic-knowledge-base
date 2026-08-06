# ADR-004: Data Layer & Theming for the Web App

## Status

Proposed (Phase 1).

## Context

The research page needs to:
- Mutate state (upload a document).
- Poll a job status endpoint every 3 seconds until `done|failed`.
- Open a WebSocket, accumulate transient progress stages, and cache the
  final run for refetch on navigation.
- Support light/dark themes with system-preference detection and a manual
  override, without SSR hydration mismatch.

Per `docs/conventions.md` rule 6, any library not in the Approved Libraries
table requires an ADR. None of `@tanstack/react-query`, `next-themes`,
`lucide-react`, `clsx`, or `tailwind-merge` are currently approved.

## Decision

Add one runtime library to `apps/web/package.json`:

| Package | Purpose | Why this one |
|---|---|---|
| `@tanstack/react-query` ^5 | Server-state: mutations, polling, caching, refetch | Industry standard for React server-state. Handles the upload→poll→cache lifecycle cleanly. |

Icons are built as **inline SVG components** (zero deps). Class composition
uses a 5-line `cn()` helper (no `clsx`/`tailwind-merge`). Dark mode uses
**CSS custom properties + `prefers-color-scheme`** (no `next-themes`).
Styling uses **CSS modules** (no Tailwind). See decisions D-017 and D-011.

## Consequences

### Positive

- React Query eliminates manual cache/poll wiring for the upload→job→run
  flow. The `features/research/api/` hooks map 1:1 to its primitives
  (`useMutation`, `useQuery`, `QueryClient`).
- Only one runtime dependency added — the rest (icons, class composition,
  theming, styling) are solved with native CSS modules, inline SVG, a 5-line
  `cn()` helper, and CSS custom properties.

### Negative / mitigations

| Risk | Mitigation |
|---|---|
| New dependency not in Approved Libraries | This ADR adds it (see below). |
| React Query is overkill for a single page | It scales to `/library` and `/runs` in Phase 2 without a rewrite. The bundle cost is ~13kb gzipped — acceptable. |

## Approved Libraries update

Add to `docs/conventions.md` → Approved Libraries table:

| Concern | Library |
|---|---|
| Server state / data fetching | @tanstack/react-query |

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Native `fetch` + `useState` (no React Query) | Works, but manual cache/poll wiring duplicates what React Query provides. More code, more edge cases, no refetch-on-focus. Chosen only if zero new deps is a hard constraint. |
| SWR (Vercel) | Similar capability, but React Query has better mutation + devtools support and is more widely adopted. |
| `next-themes` alternative: manual `prefers-color-scheme` listener | Reinvents what `next-themes` already does, including the hydration guard. More bug surface. |
| Tailwind-only theming (CSS vars only, no provider) | Cannot detect system preference or persist manual override without JS. |

## Scope note

This ADR covers **only** the data-layer and theming libraries. It does not
cover agent-framework or routing libraries (see Phase 2 for TanStack AI,
which would need its own ADR).
