/**
 * features/research/api/use-research-run.ts
 * ------------------------------------------
 * Purpose:    Research run lifecycle driven by the AG-UI SSE stream.
 *             The research chat owns the SSE connection (useResearchChat);
 *             this hook is the pure reducer that turns stream events
 *             (stage / citations / RUN_FINISHED / RUN_ERROR) into the
 *             transient run state the UI renders. No separate WebSocket.
 * Dependencies: @tanstack/react-query, utils/parse-citations.ts
 * Scope:      Research run flow.
 */

import { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getRunDetail } from "../research-service";
import type { Citation } from "../utils/parse-citations";

export type { Citation };

/** Events the chat SSE stream emits that this reducer understands. */
export type RunEvent =
  | { type: "STAGE"; stage: string }
  | { type: "CITATIONS"; runId: string; citations: Citation[] }
  | { type: "RUN_FINISHED"; runId: string }
  | { type: "RUN_ERROR"; code: string; message: string };

export interface ResearchRunState {
  status: "idle" | "connecting" | "running" | "complete" | "error";
  stages: string[];
  citations: Citation[];
  runId: string | null;
  error: string | null;
}

const INITIAL_STATE: ResearchRunState = {
  status: "idle",
  stages: [],
  citations: [],
  runId: null,
  error: null,
};

export function useResearchRun() {
  const [state, setState] = useState<ResearchRunState>(INITIAL_STATE);
  const queryClient = useQueryClient();

  /** Reset run state before a new question is submitted via SSE. */
  const beginRun = useCallback(() => {
    setState({ ...INITIAL_STATE, status: "connecting" });
  }, []);

  /** Fold one stream event into run state. */
  const applyEvent = useCallback(
    (event: RunEvent) => {
      if (event.type === "RUN_FINISHED") {
        // The run is persisted server-side; drop any stale list snapshot so the
        // runs page refetches and shows it.
        queryClient.invalidateQueries({ queryKey: ["runs"] });
      }

      setState((prev) => {
        switch (event.type) {
          case "STAGE":
            return {
              ...prev,
              status: "running",
              stages: prev.stages.includes(event.stage)
                ? prev.stages
                : [...prev.stages, event.stage],
            };
          case "CITATIONS":
            return { ...prev, citations: event.citations, runId: prev.runId ?? event.runId };
          case "RUN_FINISHED":
            return { ...prev, status: "complete", runId: prev.runId ?? event.runId };
          case "RUN_ERROR":
            return { ...prev, status: "error", error: event.message };
        }
      });
    },
    [queryClient],
  );

  const reset = useCallback(() => setState(INITIAL_STATE), []);

  return { state, beginRun, applyEvent, reset };
}

export function useRunDetail(runId: string | null) {
  return useQuery({
    queryKey: ["run", runId] as const,
    queryFn: () => getRunDetail(runId!),
    enabled: runId !== null,
  });
}
