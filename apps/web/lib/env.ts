/**
 * lib/env.ts
 * ----------
 * Purpose:    Environment variable access + runtime validation.
 *             Fails fast with a clear error if required vars are missing.
 * Dependencies: none
 * Scope:      App-wide config.

 * NEXT_PUBLIC_* vars are inlined at build time by Next.js.
 */

function required(name: string, fallback?: string): string {
  const value = process.env[name] ?? fallback;
  if (value === undefined) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

export const API_BASE_URL = required(
  "NEXT_PUBLIC_API_BASE_URL",
  "http://localhost:8000",
);

const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_BASE_URL;

export const WS_BASE_URL_RESOLVED: string =
  WS_BASE_URL ?? API_BASE_URL.replace(/^http/, "ws");
