"use client";

import { fetchServerSentEvents, useChat } from "@tanstack/ai-react";
import type { UIMessage } from "@tanstack/ai-client";
import { API_BASE_URL } from "@/lib/env";
import { clearHistory, copyAnswer } from "./research-tools";

const connection = fetchServerSentEvents(`${API_BASE_URL}/api/research/chat`);

export function useResearchChat(threadId: string, initialMessages: UIMessage[] = []) {
  return useChat({
    connection,
    tools: [clearHistory, copyAnswer],
    initialMessages,
    threadId,
  });
}
