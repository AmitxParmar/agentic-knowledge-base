/**
 * features/research/api/ws-transport.ts
 * -------------------------------------
 * Purpose:    Custom TanStack AI connection adapter that wraps our existing
 *             WebSocket research endpoint. Maps the backend's custom WS protocol
 *             (progress/answer events) to AG-UI StreamChunks so TanStack AI's
 *             useChat can drive UI state without any backend change.
 * Dependencies: @tanstack/ai-client (stream), @tanstack/ai (StreamChunk), lib/env.ts
 * Scope:      TanStack AI transport layer (one adapter for the research page).

 * AG-UI events produced (from our WS messages):
 *   WS {type:"progress", stage}  → TEXT_MESSAGE_CONTENT delta (live progress text)
 *   WS {type:"answer", text}     → TEXT_MESSAGE_CONTENT delta (answer text)
 *   WS {type:"done"}             → (no-op; answer already streamed)
 *   WS {type:"error", message}   → RUN_ERROR
 */

import { stream } from "@tanstack/ai-client";
import type { StreamChunk } from "@tanstack/ai";
import { WS_BASE_URL_RESOLVED } from "@/lib/env";

function createId(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Create a TanStack AI connection adapter backed by our research WebSocket.
 *
 * Each sendMessage opens a fresh WS (matching current single-shot behavior),
 * streams progress deltas + answer text as AG-UI text chunks, then closes.
 */
export function createWsResearchConnection(threadId: string) {
  return stream((messages) => {
    const runId = createId("run");
    const messageId = createId("msg");
    const question = extractQuestion(messages);

    return (async function* (): AsyncGenerator<StreamChunk> {
      if (!question) {
        yield { type: "RUN_ERROR", message: "No question provided.", code: "WS_ERROR" } as StreamChunk;
        return;
      }

      yield { type: "RUN_STARTED", threadId, runId } as StreamChunk;
      yield { type: "TEXT_MESSAGE_START", messageId, role: "assistant" } as StreamChunk;

      const ws = new WebSocket(`${WS_BASE_URL_RESOLVED}/api/research/ws`);

      yield* wsMessageGenerator(ws, question, messageId, runId, threadId);
    })();
  });
}

async function* wsMessageGenerator(
  ws: WebSocket,
  question: string,
  messageId: string,
  runId: string,
  threadId: string,
): AsyncGenerator<StreamChunk> {
  const queue: Array<StreamChunk | { error: Error }> = [];
  let resolver: (() => void) | null = null;
  let done = false;

  function push(value: StreamChunk) {
    queue.push(value);
    resolver?.();
  }

  function fail(error: Error) {
    queue.push({ error });
    resolver?.();
  }

  ws.onopen = () => {
    ws.send(JSON.stringify({ question }));
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as {
        type: string;
        stage?: string;
        text?: string;
        message?: string;
      };

      if (data.type === "progress" && data.stage) {
        push({ type: "TEXT_MESSAGE_CONTENT", messageId, delta: `${data.stage}\n` } as StreamChunk);
      } else if (data.type === "answer" && data.text) {
        push({ type: "TEXT_MESSAGE_CONTENT", messageId, delta: data.text } as StreamChunk);
      } else if (data.type === "error") {
        push({ type: "RUN_ERROR", message: data.message ?? "Unknown error.", code: "WS_ERROR" } as StreamChunk);
        ws.close();
      }
    } catch {
      // Ignore malformed messages.
    }
  };

  ws.onerror = () => {
    fail(new Error("WebSocket connection failed."));
  };

  ws.onclose = () => {
    done = true;
    resolver?.();
  };

  try {
    while (!done || queue.length > 0) {
      while (queue.length > 0) {
        const item = queue.shift()!;
        if ("error" in item) throw item.error;
        yield item;
      }

      if (!done) {
        await new Promise<void>((resolve) => {
          resolver = resolve;
        });
      }
    }
  } finally {
    ws.close();
    yield { type: "TEXT_MESSAGE_END", messageId } as StreamChunk;
    yield { type: "RUN_FINISHED", threadId, runId } as StreamChunk;
  }
}

function extractQuestion(messages: unknown[]): string | null {
  if (!Array.isArray(messages) || messages.length === 0) return null;
  const last = messages[messages.length - 1] as {
    role?: string;
    parts?: Array<{ type: string; content?: string }>;
  };
  if (last.role !== "user" || !last.parts) return null;
  const textParts = last.parts
    .filter((p) => p.type === "text" && p.content)
    .map((p) => p.content!);
  return textParts.length > 0 ? textParts.join("") : null;
}
