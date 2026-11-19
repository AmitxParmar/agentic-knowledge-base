/**
 * features/devicehub/api/client.ts
 * --------------------------------
 * Purpose:    Browser client for the same-origin DeviceHub proxy routes.
 *             Distinguishes "hub is waking up" from real failures so the UI
 *             can say the right thing.
 * Dependencies: none
 * Scope:      Dashboard data fetching.
 */

export type DashboardFailure =
  | "warming"
  | "unauthorized"
  | "not_found"
  | "unconfigured"
  | "http_error"
  | "network";

export class DashboardError extends Error {
  constructor(
    readonly failure: DashboardFailure,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "DashboardError";
  }
}

function classify(status: number, code: string | undefined): DashboardFailure {
  if (code === "unconfigured") return "unconfigured";
  if (code === "timeout" || code === "unreachable") return "warming";
  if (status === 403 || status === 401 || status === 502) return "unauthorized";
  if (status === 404) return "not_found";
  if (status === 503 || status === 504) return "warming";
  return "http_error";
}

export async function getJson<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { signal, cache: "no-store" });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new DashboardError(
      "network",
      0,
      err instanceof Error ? err.message : "request failed",
    );
  }

  if (!res.ok) {
    let code: string | undefined;
    let message = `request failed (${res.status})`;
    try {
      const body: unknown = await res.json();
      if (body && typeof body === "object") {
        const record = body as Record<string, unknown>;
        if (typeof record.error === "string") code = record.error;
        if (typeof record.message === "string") message = record.message;
      }
    } catch {
      // Non-JSON error body; keep the status-derived message.
    }
    throw new DashboardError(classify(res.status, code), res.status, message);
  }

  return (await res.json()) as T;
}

/** Human copy for each failure mode, used by both list and detail views. */
export function describeFailure(error: unknown): {
  title: string;
  detail: string;
  retryable: boolean;
} {
  if (!(error instanceof DashboardError)) {
    return {
      title: "Something went wrong",
      detail: "The dashboard could not load telemetry.",
      retryable: true,
    };
  }

  switch (error.failure) {
    case "warming":
      return {
        title: "Waking the device hub",
        detail:
          "The free-tier Rust service sleeps when idle and can take up to a minute to start. Retry in a moment.",
        retryable: true,
      };
    case "unconfigured":
      return {
        title: "Dashboard is not configured",
        detail:
          "Set HUB_API_URL and HUB_API_TOKEN for the web app, then restart the dev server.",
        retryable: false,
      };
    case "unauthorized":
      return {
        title: "Hub rejected the token",
        detail:
          "HUB_API_TOKEN on the web app does not match HUB_API_TOKEN on the hub.",
        retryable: false,
      };
    case "not_found":
      return {
        title: "Device not found",
        detail: "That device id is not registered in the hub.",
        retryable: false,
      };
    case "network":
      return {
        title: "Cannot reach the dashboard",
        detail: "Check that the Next.js dev server is running.",
        retryable: true,
      };
    default:
      return {
        title: "Telemetry request failed",
        detail: error.message,
        retryable: true,
      };
  }
}
