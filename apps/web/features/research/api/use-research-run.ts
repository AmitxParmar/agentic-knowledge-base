/**
 * features/research/api/use-research-run.ts
 * -----------------------------------------
 * Purpose:    Research run lifecycle over WebSocket.
 *             Owns transient progress stages locally (not React Query —
 *             stages are transient events, not server state).
 *             Caches the completed run_id in React Query so useRunDetail
 *             can hydrate on navigation without re-running.
 * Dependencies: @tanstack/react-query, hooks/use-research-ws.ts, utils/ws-adapter.ts
 * Scope:      Research run flow.
 */

import { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useResearchWs } from "../hooks/use-research-ws";
import { getRunDetail } from "../research-service";
import type { Citation } from "../utils/ws-adapter";

export type { Citation };

export interface ResearchRunState {
  status: "idle" | "connecting" | "running" | "complete" | "error";
  stages: string[];
  answer: string | null;
  citations: Citation[];
  runId: string | null;
  error: string | null;
}

const INITIAL_STATE: ResearchRunState = {
  status: "idle",
  stages: [],
  answer: null,
  citations: [],
  runId: null,
  error: null,
};

export function useResearchRun() {
  const [state, setState] = useState<ResearchRunState>(INITIAL_STATE);
  const { startRun, abort } = useResearchWs();
  const queryClient = useQueryClient();

  const startResearch = useCallback(
    (question: string) => {
      setState({ ...INITIAL_STATE, status: "connecting" });

      startRun(question, {
        onStage: (stage) => {
          setState((prev) => ({
            ...prev,
            status: "running",
            stages: [...prev.stages, stage],
          }));
        },
        onAnswer: (runId, text, citations) => {
          setState((prev) => ({
            ...prev,
            status: "complete",
            answer: text,
            citations,
            runId,
          }));
          queryClient.setQueryData(["run", runId], {
            run_id: runId,
            question,
            answer: text,
            status: "complete",
            citations: citations.map((c) => ({ chunk_id: c.chunk_id })),
            created_at: new Date().toISOString(),
          });
        },
        onError: (message) => {
          setState((prev) => ({ ...prev, status: "error", error: message }));
        },
        onDone: () => {
          // Final handled by onAnswer; this is a trailing signal.
        },
      });
    },
    [startRun, queryClient],
  );

  const reset = useCallback(() => {
    abort();
    setState(INITIAL_STATE);
  }, [abort]);

  return { state, startResearch, reset, abort };
}

export function useRunDetail(runId: string | null) {
  return useQuery({
    queryKey: ["run", runId] as const,
    queryFn: () => getRunDetail(runId!),
    enabled: runId !== null,
  });
}
