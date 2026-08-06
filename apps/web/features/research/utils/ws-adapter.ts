/**
 * features/research/utils/ws-adapter.ts
 * -------------------------------------
 * Purpose:    Parse raw WebSocket message data into typed events.
 *             Enforces the fixed vocabulary from docs/ux.md.
 * Dependencies: none
 * Scope:      Research WebSocket consumer.
 */

export type WsEvent =
  | { type: "progress"; stage: string }
  | { type: "answer"; run_id: string; text: string; citations: Citation[] }
  | { type: "done" }
  | { type: "error"; message: string };

export interface Citation {
  chunk_id: string;
  source_ref: string;
  relevance_score: number;
}

export function parseWsMessage(data: string): WsEvent | null {
  try {
    const parsed = JSON.parse(data) as WsEvent;
    if (parsed && typeof parsed === "object" && "type" in parsed) {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}
