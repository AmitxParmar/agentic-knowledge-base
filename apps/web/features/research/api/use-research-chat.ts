/**
 * features/research/api/use-research-chat.ts
 * ------------------------------------------
 * Purpose:    TanStack AI useChat wrapper for the research page.
 *             Uses the AG-UI SSE endpoint (Option B, ADR-005) for chat state
 *             with client tools for copy/clear.
 * Dependencies: @tanstack/ai-react (useChat, fetchServerSentEvents),
 *               research-tools.ts, lib/env.ts
 * Scope:      Research page chat state.
 */

"use client";

import { fetchServerSentEvents, useChat } from "@tanstack/ai-react";
import { API_BASE_URL } from "@/lib/env";
import { clearHistory, copyAnswer } from "./research-tools";

const connection = fetchServerSentEvents(`${API_BASE_URL}/api/research/chat`);

export function useResearchChat(threadId: string) {
  return useChat({
    connection,
    tools: [clearHistory, copyAnswer],
    initialMessages: [],
    threadId,
  });
}
