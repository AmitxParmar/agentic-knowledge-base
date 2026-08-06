/**
 * features/research/hooks/use-research-ws.ts
 * ------------------------------------------
 * Purpose:    Raw WebSocket wrapper for the research run endpoint.
 *             Lifecycle guards, safe JSON parsing, abort support.
 * Dependencies: lib/env.ts, utils/ws-adapter.ts
 * Scope:      Research run lifecycle.
 */

import { useCallback, useRef } from "react";
import { WS_BASE_URL_RESOLVED } from "@/lib/env";
import { parseWsMessage, type Citation } from "../utils/ws-adapter";

export interface ResearchRunState {
  status: "idle" | "connecting" | "running" | "complete" | "error";
  stages: string[];
  answer: string | null;
  citations: Citation[];
  runId: string | null;
  error: string | null;
}

export function useResearchWs() {
  const wsRef = useRef<WebSocket | null>(null);

  const startRun = useCallback(
    (question: string, handlers: {
      onStage: (stage: string) => void;
      onAnswer: (runId: string, text: string, citations: Citation[]) => void;
      onError: (message: string) => void;
      onDone: () => void;
    }) => {
      const ws = new WebSocket(`${WS_BASE_URL_RESOLVED}/api/research/ws`);
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({ question }));
      };

      ws.onmessage = (event) => {
        const message = parseWsMessage(event.data);
        if (!message) return;

        if (message.type === "progress") {
          handlers.onStage(message.stage);
        }

        if (message.type === "answer") {
          handlers.onAnswer(message.run_id, message.text, message.citations as never);
        }

        if (message.type === "error") {
          handlers.onError(message.message);
        }

        if (message.type === "done") {
          handlers.onDone();
          ws.close();
        }
      };

      ws.onerror = () => {
        handlers.onError("WebSocket connection failed.");
      };
    },
    [],
  );

  const abort = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  return { startRun, abort };
}
