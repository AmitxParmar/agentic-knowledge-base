/**
 * features/devicehub/api/use-devices.ts
 * -------------------------------------
 * Purpose:    Fleet list, refreshed on an interval so online/offline state
 *             catches up without a reload.
 * Dependencies: @tanstack/react-query, client.ts
 * Scope:      Dashboard fleet view.
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import type { DeviceSummary } from "@/features/devicehub/types";
import { getJson } from "./client";

export const deviceHubKeys = {
  devices: ["devicehub", "devices"] as const,
  device: (id: string) => ["devicehub", "device", id] as const,
  telemetry: (id: string) => ["devicehub", "telemetry", id] as const,
};

export function useDevices() {
  return useQuery({
    queryKey: deviceHubKeys.devices,
    queryFn: ({ signal }) => getJson<DeviceSummary[]>("/api/devicehub/devices", signal),
    // No automatic retries: a cold start already takes a minute, and the
    // error state offers an explicit retry instead of doubling the wait.
    retry: false,
    staleTime: 5_000,
    refetchInterval: 15_000,
  });
}
