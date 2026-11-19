/**
 * lib/devicehub.ts
 * ----------------
 * Purpose:    Server-only client for the DeviceHub read API (`apps/hub`).
 *             The hub is protected by a bearer token, and `EventSource`
 *             cannot send headers, so the browser never calls the hub
 *             directly: every dashboard request goes through the same-origin
 *             proxy routes in `app/api/devicehub/*`, which use this module.
 * Dependencies: none (global fetch)
 * Scope:      Route handlers and server code only. Importing this from a
 *             client component would leak `HUB_API_TOKEN` into the bundle.
 */

import type {
  DeviceStateEvent,
  DeviceSummary,
  TelemetryRow,
} from "@/features/devicehub/types";

/** A Render free instance can take 30–60 s to wake up. */
const DEFAULT_TIMEOUT_MS = 45_000;

function clean(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed.replace(/\/+$/, "") : undefined;
}

const HUB_API_URL = clean(process.env.HUB_API_URL) ?? "http://localhost:8080";
const HUB_API_TOKEN = clean(process.env.HUB_API_TOKEN);

export type HubFailure =
  | "unconfigured"
  | "timeout"
  | "unreachable"
  | "unauthorized"
  | "upstream";

export class HubError extends Error {
  constructor(
    readonly kind: HubFailure,
    message: string,
  ) {
    super(message);
    this.name = "HubError";
  }
}

interface HubRequestInit {
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** `0` disables the timeout — required for the SSE stream. */
  timeoutMs?: number;
}

export async function hubFetch(
  path: string,
  init: HubRequestInit = {},
): Promise<Response> {
  if (!HUB_API_TOKEN) {
    throw new HubError(
      "unconfigured",
      "HUB_API_TOKEN is not set; the dashboard cannot reach the hub",
    );
  }

  const timeoutMs = init.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  const timer =
    timeoutMs > 0 ? setTimeout(() => controller.abort(), timeoutMs) : undefined;
  const forwardAbort = () => controller.abort();
  init.signal?.addEventListener("abort", forwardAbort);

  try {
    return await fetch(`${HUB_API_URL}${path}`, {
      headers: {
        authorization: `Bearer ${HUB_API_TOKEN}`,
        ...(init.headers ?? {}),
      },
      signal: controller.signal,
      cache: "no-store",
    });
  } catch (err) {
    if (controller.signal.aborted && !init.signal?.aborted) {
      throw new HubError(
        "timeout",
        `hub did not answer within ${Math.round(timeoutMs / 1000)} s`,
      );
    }
    throw new HubError(
      "unreachable",
      err instanceof Error ? err.message : "hub unreachable",
    );
  } finally {
    if (timer) clearTimeout(timer);
    init.signal?.removeEventListener("abort", forwardAbort);
  }
}

/**
 * Pass a hub JSON response through unchanged. Status and body are the hub's;
 * only transport failures (cold start, misconfiguration) are rewritten.
 */
export async function proxyJson(path: string): Promise<Response> {
  try {
    const upstream = await hubFetch(path, {
      headers: { accept: "application/json" },
    });
    const body = await upstream.text();
    return new Response(body, {
      status: upstream.status,
      headers: {
        "content-type": "application/json",
        "cache-control": "no-store",
      },
    });
  } catch (err) {
    return errorResponse(err);
  }
}

export function errorResponse(err: unknown): Response {
  const failure =
    err instanceof HubError
      ? err
      : new HubError(
          "upstream",
          err instanceof Error ? err.message : "unknown hub failure",
        );

  // 504 tells the UI "this is a cold start, retry", 502 a rejected token,
  // 503 everything else. The hub's own 4xx/5xx are never rewritten.
  const status =
    failure.kind === "timeout"
      ? 504
      : failure.kind === "unauthorized"
        ? 502
        : 503;

  return Response.json(
    { error: failure.kind, message: failure.message },
    { status, headers: { "cache-control": "no-store" } },
  );
}

export type { DeviceStateEvent, DeviceSummary, TelemetryRow };
