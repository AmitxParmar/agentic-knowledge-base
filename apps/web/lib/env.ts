/**
 * lib/env.ts
 * ----------
 * Purpose:    Environment variable access + runtime validation.
 *             Fails fast with a clear error if required vars are missing.
 * Dependencies: none
 * Scope:      App-wide config.

 * NEXT_PUBLIC_* vars are inlined at build time by Next.js.
 */

// NOTE: Next.js inlines NEXT_PUBLIC_* vars at build time by statically
// replacing `process.env.NEXT_PUBLIC_X` references. Dynamic access like
// `process.env[name]` is NOT inlined and reads as undefined in the browser,
// which is why the app silently fell back to localhost:8000. Keep every
// access below a string literal so the bundler can replace it.
function clean(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  // Treat empty string as missing and strip trailing slashes so
  // `${API_BASE_URL}/api/...` never becomes a double-slash URL.
  return trimmed ? trimmed.replace(/\/+$/, "") : undefined;
}

export const API_BASE_URL =
  clean(process.env.NEXT_PUBLIC_API_BASE_URL) ??
  clean(process.env.NEXT_PUBLIC_API_URL) ??
  "http://localhost:8000";
