/**
 * features/devicehub/api/use-telemetry.ts
 * ---------------------------------------
 * Purpose:    Historical telemetry for one device. The hub returns newest
 *             first and caps `limit` at 500, which is also the chart window.
 * Dependencies: @tanstack/react-query, client.ts
 * Scope:      Dashboard detail view.
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import type { TelemetryRow } from "@/features/devicehub/types";
import { getJson } from "./client";
import { deviceHubKeys } from "./use-devices";

/** Matches `MAX_LIMIT` in the hub's read API. */
export const TELEMETRY_WINDOW = 500;

export function useTelemetry(deviceId: string) {
  return useQuery({
    queryKey: deviceHubKeys.telemetry(deviceId),
    queryFn: ({ signal }) =>
      getJson<TelemetryRow[]>(
        `/api/devicehub/devices/${encodeURIComponent(deviceId)}/telemetry?limit=${TELEMETRY_WINDOW}`,
        signal,
      ),
    enabled: deviceId.length > 0,
    retry: false,
    staleTime: 5_000,
    // Live data arrives over SSE; this is only a safety net for missed frames.
    refetchInterval: 60_000,
  });
}
