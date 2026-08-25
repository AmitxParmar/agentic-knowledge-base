/**
 * features/research/api/use-model-info.ts
 * ---------------------------------------
 * Purpose:    Fetches active LLM via gateway for header badge.
 *             No auth required — exposes only model names, not keys.
 */
"use client";

import { useQuery } from "@tanstack/react-query";
import { API_BASE_URL } from "@/lib/env";

export interface ModelInfo {
  provider: string;
  model: string;
  primary: string;
  fallback: string;
  fallback_model: string;
}

export function useModelInfo() {
  return useQuery<ModelInfo>({
    queryKey: ["model-info"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/api/research/model-info`);
      if (!res.ok) throw new Error(`model-info ${res.status}`);
      return (await res.json()) as ModelInfo;
    },
    staleTime: 60_000,
    retry: 1,
  });
}
