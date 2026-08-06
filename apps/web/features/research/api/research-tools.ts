/**
 * features/research/api/research-tools.ts
 * ---------------------------------------
 * Purpose:    Client-side tools for the research chat.
 *             Defined once via toolDefinition(), implemented with .client().
 * Dependencies: @tanstack/ai (toolDefinition), zod
 * Scope:      TanStack AI client tools.
 */

import { toolDefinition } from "@tanstack/ai";
import { z } from "zod";

export const clearHistoryTool = toolDefinition({
  name: "clearHistory",
  description: "Clear the conversation history on the research page.",
  inputSchema: z.object({}),
  outputSchema: z.object({ cleared: z.boolean() }),
});

export const copyAnswerTool = toolDefinition({
  name: "copyAnswer",
  description: "Copy the latest answer text to the clipboard.",
  inputSchema: z.object({
    text: z.string().describe("The answer text to copy."),
  }),
  outputSchema: z.object({ copied: z.boolean() }),
});

export const clearHistory = clearHistoryTool.client(() => {
  return { cleared: true };
});

export const copyAnswer = copyAnswerTool.client(async (input) => {
  try {
    await navigator.clipboard.writeText(input.text);
    return { copied: true };
  } catch {
    return { copied: false };
  }
});
