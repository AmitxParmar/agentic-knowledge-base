/**
 * features/research/api/use-research-chat.ts
 * ------------------------------------------
 * Purpose:    TanStack AI useChat wrapper for the research page.
 *             Manages chat state (messages, loading, error) over our WS,
 *             with client tools for copy/clear.
 * Dependencies: @tanstack/ai-react (useChat), ws-transport.ts, research-tools.ts
 * Scope:      Research page chat state.
 */

"use client";

import { useChat } from "@tanstack/ai-react";
import { createWsResearchConnection } from "./ws-transport";
import { clearHistory, copyAnswer } from "./research-tools";

const THREAD_ID = "research-main";

const connection = createWsResearchConnection(THREAD_ID);

export function useResearchChat() {
  return useChat({
    connection,
    tools: [clearHistory, copyAnswer],
    initialMessages: [],
  });
}
