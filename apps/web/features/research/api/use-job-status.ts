/**
 * features/research/api/use-job-status.ts
 * ---------------------------------------
 * Purpose:    Polling query → GET /api/ingestion/jobs/{id}.
 *             Refetches every 3 seconds; stops on done|failed.
 * Dependencies: @tanstack/react-query, research-service.ts
 * Scope:      Ingestion job polling.
 */

import { useQuery } from "@tanstack/react-query";
import { getJobStatus } from "../research-service";

const TERMINAL_STAGES = new Set(["done", "failed"]);

export function useJobStatus(jobId: string | null) {
  return useQuery({
    queryKey: ["job", jobId] as const,
    queryFn: () => getJobStatus(jobId!),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const stage = query.state.data?.stage;
      if (stage && TERMINAL_STAGES.has(stage)) {
        return false;
      }
      return 3000;
    },
  });
}
