/**
 * features/research/api/use-research-chat.ts
 * -------------------------------------------
 * Purpose:    TanStack AI useChat hook bound to the AG-UI SSE endpoint.
 *             The chat stream is the single execution path: the same SSE
 *             connection carries the answer, and CUSTOM stage/citations
 *             events are forwarded to the run-state reducer via onRunEvent.
 * Dependencies: @tanstack/ai-client, @tanstack/ai-react, lib/env.ts,
 *               api/use-research-run.ts (RunEvent type)
 * Scope:      Research chat conversation surface.
 */

"use client";

import { fetchServerSentEvents, useChat } from "@tanstack/ai-react";
import type { UIMessage } from "@tanstack/ai-client";
import { API_BASE_URL } from "@/lib/env";
import { clearHistory, copyAnswer } from "./research-tools";
import type { Citation } from "../utils/parse-citations";
import type { RunEvent } from "./use-research-run";

interface StagePayload {
  stage?: string;
}

interface CitationsPayload {
  run_id?: string;
  citations?: Citation[];
}

const connection = fetchServerSentEvents(`${API_BASE_URL}/api/research/chat`);

export function useResearchChat(
  threadId: string,
  initialMessages: UIMessage[] = [],
  onRunEvent?: (event: RunEvent) => void,
) {
  return useChat({
    connection,
    tools: [clearHistory, copyAnswer],
    initialMessages,
    threadId,
    onCustomEvent: (eventType, data) => {
      if (!onRunEvent) return;

      // Progress stages and citations ride the AG-UI CUSTOM event channel so
      // they render in the progress strip / citation list instead of the
      // answer bubble. The SDK normalizes the wire events into
      // (name, value) pairs passed to onCustomEvent.
      if (eventType === "stage") {
        const payload = data as StagePayload | undefined;
        if (payload?.stage) onRunEvent({ type: "STAGE", stage: payload.stage });
      } else if (eventType === "citations") {
        const payload = data as CitationsPayload | undefined;
        onRunEvent({
          type: "CITATIONS",
          runId: payload?.run_id ?? "",
          citations: payload?.citations ?? [],
        });
      }
    },
    onChunk: (chunk) => {
      if (!onRunEvent) return;

      // Terminal events carry the run id for history linking.
      if (chunk.type === "RUN_FINISHED") {
        onRunEvent({ type: "RUN_FINISHED", runId: chunk.runId ?? "" });
      } else if (chunk.type === "RUN_ERROR") {
        onRunEvent({
          type: "RUN_ERROR",
          code: chunk.code ?? "AGENT_ERROR",
          message: chunk.message ?? "An error occurred during the research run.",
        });
      }
    },
  });
}
