/**
 * features/research/api/use-usage.ts
 * ----------------------------------
 * Purpose:    Fetches per-user token spend vs the daily budget for the
 *             usage dashboard. Powers budget visibility, not enforcement
 *             (enforcement lives server-side in run_agent).
 */
"use client";

import { useQuery } from "@tanstack/react-query";
import { API_BASE_URL } from "@/lib/env";

export interface UsageSummary {
  today_tokens: number;
  month_tokens: number;
  daily_budget: number | null;
  over_budget: boolean;
  pct_used: number | null;
}

export function useUsage() {
  return useQuery<UsageSummary>({
    queryKey: ["usage"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/api/research/usage`);
      if (!res.ok) throw new Error(`usage ${res.status}`);
      return (await res.json()) as UsageSummary;
    },
    staleTime: 30_000,
    retry: 1,
  });
}
