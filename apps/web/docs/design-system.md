# Design System — Research Workspace

## Purpose

The minimal editorial visual language for the Agentic Research Workspace.
Defines tokens, typography, layout, motion, and accessibility constraints.
This is the single source of truth for all visual decisions in Phase 1.

## Dependencies

- `apps/web/docs/README.md` — Phase 1 master spec
- `apps/web/app/layout.tsx` — font wiring
- `apps/web/app/globals.css` — token definition file

## Scope

Visual design only. Component structure lives in `README.md` → file map.

---

## 1. Color tokens

Defined as CSS custom properties (HSL components, no alpha) so
`hsl(var(--token))` references stay consistent across CSS modules.
Dark mode flips foreground/background; borders stay low-contrast in both.

### Light mode

```css
:root {
  --background: 0 0% 100%;          /* paper */
  --foreground: 222 47% 11%;        /* near-black ink */
  --muted: 210 40% 96%;             /* soft panel */
  --muted-foreground: 215 16% 47%;
  --accent: 221 83% 53%;            /* single restrained blue */
  --accent-foreground: 0 0% 100%;
  --border: 214 32% 91%;            /* hairline */
  --destructive: 0 84% 60%;
  --success: 142 71% 45%;
  --warning: 38 92% 50%;
  --ring: 221 83% 53%;
}
```

### Dark mode

```css
.dark {
  --background: 222 47% 6%;
  --foreground: 210 40% 96%;
  --muted: 217 33% 12%;
  --muted-foreground: 215 20% 65%;
  --accent: 217 91% 60%;
  --accent-foreground: 0 0% 100%;
  --border: 217 33% 18%;
  --destructive: 0 62% 50%;
  --success: 142 71% 45%;
  --warning: 38 92% 50%;
  --ring: 217 91% 60%;
}
```

### Usage rule

**Raw hex is banned from components.** Always reference
`hsl(var(--token))`. This keeps theme switching centralized and prevents
drift between light/dark contrast ratios.

### Stage-state colors

State | Token | Icon
---|---|---
Pending | `--muted-foreground` | ○
Active | `--accent` | ● (pulse)
Complete | `--success` | ✓
Failed | `--destructive` | ✕

Color alone never indicates state — always icon + text + color.

---

## 2. Typography

Loaded locally via `next/font` (zero CLS, zero runtime fetch, offline-friendly).

### Font stack

| Role | Family | CSS variable |
|---|---|---|
| Body / UI / display | Geist Sans | `--font-geist-sans` |
| Code / citations / metadata | JetBrains Mono | `--font-geist-mono` |

### Type scale

| Role | Font | Size | Line-height | Letter-spacing | Weight |
|---|---|---|---|---|---|
| Body / UI | Geist Sans | 15px | 1.6 | -0.011em | 400 |
| Small / metadata | Geist Sans | 13px | 1.5 | 0 | 400 |
| Code / citation | JetBrains Mono | 13px | 1.55 | 0 | 400 |
| Display / H1 | Geist Sans | 30px / 32px | 1.2 | -0.022em | 600 |
| Answer body | Geist Sans | 16px | 1.7 | -0.011em | 400 |

### Rules

- Body base is **15px** — never go below 12px anywhere.
- Answer body is **16px** with 1.7 line-height — long research answers must stay readable.
- Geist Sans and JetBrains Mono are self-hosted via `next/font` — no Google Fonts runtime fetch, no layout shift.

---

## 3. Spacing & layout

### Grid

```
[280px sidebar | minmax(0, 1fr) main]
```

- Sidebar: fixed 280px (document list, collapses to sheet on mobile).
- Main: fluid, contains chat area + answer column.
- Answer column: max-width **720px** centered — long answers stay readable.
- Sidebar and chat area scroll independently; the page itself does not scroll.

### Spacing scale (base unit 4px)

| Token | Value | Use |
|---|---|---|
| `--space-1` | 4px | tight gaps |
| `--space-2` | 8px | inline spacing |
| `--space-3` | 12px | compact padding |
| `--space-4` | 16px | standard padding |
| `--space-6` | 24px | section padding |
| `--space-8` | 32px | card padding |
| `--space-12` | 48px | section gaps |
| `--space-16` | 64px | page margins |

### Responsive breakpoints

| Breakpoint | Behavior |
|---|---|
| `<768px` | Sidebar collapses to sheet; citation panel → bottom sheet; nav → hamburger |
| `768px–1024px` | Sidebar collapses to icon rail; citation panel → right sheet |
| `>1024px` | Full sidebar + right citation panel |

---

## 4. Motion

All durations strictly in the 150–300ms tolerance.

| Interaction | Duration | Easing |
|---|---|---|
| Stage pill pending→active→complete | 200ms | ease-out |
| Citation popover open | 150ms | spring (Radix default) |
| Bottom sheet / side sheet open | 250ms | ease-out |
| Answer streaming | no animation | markdown paints as chunks arrive |
| Route transitions | 150ms | ease-out |

### Reduced motion

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

`prefers-reduced-motion` is the single gate — no JS library needed.

---

## 5. Accessibility constraints

| Rule | Implementation |
|---|---|
| Contrast ≥ 4.5:1 | Verified for all text/background pairs in both themes |
| Touch targets ≥ 44×44px | All buttons, citation refs, nav items |
| Focus rings visible | `ring-2 ring-[hsl(var(--ring))]` on `:focus-visible` |
| Screen reader stage announcements | `role="log"` `aria-live="polite"` on stage list |
| Keyboard nav | roving tabindex in segmented control, focus trap in sheets |
| No emoji as icons | All icons SVG via `lucide-react` |
| Color ≠ sole indicator | Icon + text + color for all states |

---

## 6. Iconography

- **Library:** `lucide-react` (tree-shakeable, consistent stroke width).
- **Size:** 16px default, 20px for primary actions.
- **Weight:** inherit stroke from `currentColor`.
- **No emoji** in UI, progress, or buttons (hard rule from UX guidelines).

---

## 7. Styling approach — CSS modules (no Tailwind)

This project uses **CSS custom properties + per-component CSS modules**
(`.module.css`), not Tailwind. Rationale:

- Zero new build dependencies (no `tailwindcss`, `postcss`, `autoprefixer`).
- The existing scaffold (`app/page.module.css`) already uses this pattern.
- Design tokens in `globals.css` are consumed via `hsl(var(--token))` in
  each module — single source of truth, theme-safe.

### `cn()` helper (`lib/utils.ts`)

A minimal classnames composition helper (no `clsx` dependency):

```ts
export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}
```

Used to compose CSS module classes conditionally:

```tsx
import styles from "./upload-composer.module.css";
import { cn } from "@/lib/utils";

<button className={cn(styles.button, styles.primary, disabled && styles.disabled)}>
```

### Module naming convention

- One `.module.css` per component, co-located: `foo.tsx` + `foo.module.css`.
- Class names use camelCase: `.primaryButton`, `.stagePill`, `.citationCard`.
- Global utility classes (`.visuallyHidden`, `.srOnly`) live in `globals.css`.

---

## 8. Component style reference

### Buttons

| Variant | Style |
|---|---|
| Primary | `--accent` bg, white text, `--space-3` `--space-4` padding, 8px radius |
| Secondary | `--border` border, `--foreground` text |
| Ghost | transparent, hover: `--muted` bg |
| Destructive | `--destructive` bg, white text |

### Cards

- 1px `var(--border)` border.
- `--space-6` padding.
- No shadows (flat editorial look).
- 8px radius.

### Form fields

- Visible label above input (never placeholder-only).
- `--border` border, `--space-3` padding.
- Error message inline below field in `--destructive`.
- Placeholder is example text only, never the label.
