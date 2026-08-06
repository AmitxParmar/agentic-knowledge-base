/**
 * features/research/api/use-run-history.ts
 * ----------------------------------------
 * Purpose:    Run history list query.
 * Dependencies: @tanstack/react-query, research-service.ts
 * Scope:      Runs page data.
 */

import { useQuery } from "@tanstack/react-query";
import { listRuns } from "../research-service";

export function useRunHistory() {
  return useQuery({
    queryKey: ["runs"] as const,
    queryFn: () => listRuns(),
  });
}
