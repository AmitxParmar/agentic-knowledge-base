/**
 * features/devicehub/api/use-device.ts
 * ------------------------------------
 * Purpose:    Single device summary (identity, presence, latest payload).
 * Dependencies: @tanstack/react-query, client.ts
 * Scope:      Dashboard detail view.
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import type { DeviceSummary } from "@/features/devicehub/types";
import { getJson } from "./client";
import { deviceHubKeys } from "./use-devices";

export function useDevice(deviceId: string) {
  return useQuery({
    queryKey: deviceHubKeys.device(deviceId),
    queryFn: ({ signal }) =>
      getJson<DeviceSummary>(
        `/api/devicehub/devices/${encodeURIComponent(deviceId)}`,
        signal,
      ),
    enabled: deviceId.length > 0,
    retry: false,
    staleTime: 5_000,
    refetchInterval: 15_000,
  });
}
