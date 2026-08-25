# ADR-009: Tailwind CSS v4 for the Web App

## Status

Accepted (2026-08)

## Context

The research chat surface is being rebuilt into a Perplexity-style
conversation UI (inline thinking trace, source context cards, rounded
composer). The reference designs are expressed in Tailwind utilities over a
token vocabulary (`bg-surface`, `text-ink-2`, `rounded-card`, `shadow-card`).

The current styling approach is CSS custom properties + per-component CSS
modules (`apps/web/docs/design-system.md §7`), chosen to avoid build
dependencies. Hand-porting ~15 components of interaction-heavy markup
(expand/collapse grids, staggered entrances, shimmer labels) to CSS modules
duplicates every utility as bespoke class names and slows iteration on a
surface that is mostly visual polish.

Tailwind CSS v4 changed the cost calculus vs. when §7 was written:

- **No config file required** — tokens are declared in CSS via `@theme`,
  which is exactly how `globals.css` already works.
- **No PostCSS plugin juggling beyond one package**
  (`@tailwindcss/postcss`).
- Zero runtime; generated CSS is tree-shaken to used utilities.

## Constraints

1. Design tokens stay in `globals.css` as CSS custom properties — Tailwind's
   `@theme` maps them to utilities; it does not become a second token home.
2. Raw hex remains banned from component files (`design-system.md` → Usage
   rule). Colors are referenced through theme tokens only.
3. Existing pages that still use CSS modules (`library/`, `runs/`, shared
   chrome) must keep working — migration is per-surface, not big-bang.
4. No other styling dependency is added (no framer-motion, no CSS-in-JS).
   Motion stays on CSS transitions/keyframes.

## Decision

Adopt **Tailwind CSS v4** for `apps/web` alongside existing CSS modules:

```bash
pnpm --filter web add -D tailwindcss @tailwindcss/postcss
```

- `postcss.config.mjs` registers `@tailwindcss/postcss`.
- `globals.css` declares the palette/radius/shadow/motion tokens under
  `@theme inline` so utilities like `bg-surface text-ink-2 rounded-card`
  resolve against the same variables CSS modules consume today.
- New/rebuilt feature code (research chat surface) uses Tailwind utilities.
  Legacy surfaces stay on CSS modules until touched; both approaches can
  coexist because they share the same underlying custom properties.
- CSS modules remain permitted for genuinely complex local styles
  (e.g., syntax-highlight overrides) where utilities would be noisier than
  classes.

This supersedes `apps/web/docs/design-system.md §7` ("no Tailwind"), which
is amended accordingly. Per the repo decision-authority order, an accepted
ADR outranks conventions and design docs.

## Consequences

### Positive

- Reference-grade UI ports near-verbatim instead of being re-expressed as
  hundreds of module classes.
- Token discipline improves: `@theme` makes undocumented ad-hoc colors a
  lint-visible anomaly rather than a habit.
- Smaller diff surface for visual iteration on the research workspace.

### Negative / mitigations

| Risk | Mitigation |
|---|---|
| Two styling idioms coexist during migration | Shared custom-property tokens; each file uses exactly one idiom. |
| Utility soup in TSX | Keep layout-critical dimensions as semantic tokens (`max-w-prose` style aliases); long conditional class strings composed via `cn()`. |
| Build step grows | One PostCSS plugin, dev-only dependency; output tree-shaken by usage. |

## Approved Libraries update

Add to `docs/conventions.md` → Approved Libraries table:

| Concern | Library |
|---|---|
| Web styling / utility CSS | tailwindcss + @tailwindcss/postcss (dev) |

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Port references to CSS modules | Compliant but high-churn: every animation/state variant becomes hand-maintained class pairs across ~8 module files. Slows the actual goal (Perplexity-style UX). |
| CSS-in-JS (styled-components, panda) | New runtime or codegen dep, contradicts constraint 4, no benefit over v4 here. |
| Keep terminal aesthetic, restructure only | Rejected by product direction: chat must read like Perplexity, not Tactical Telemetry. |

## Scope note

Covers styling tooling only. Component structure, progress vocabulary
(`docs/ui/ux.md`), and citation rules are unchanged.
