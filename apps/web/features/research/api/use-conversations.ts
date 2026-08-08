/**
 * features/research/api/use-conversations.ts
 * ------------------------------------------
 * Purpose:    Client-side conversation thread store. Multiple threads, each
 *             holding its title + message list, ordered by recency. Local-only
 *             for now — the per-thread message shape matches TanStack AI's
 *             UIMessage so it can swap to server persistence later.
 * Dependencies: react (no network)
 * Scope:      Research chat conversation history.
 */

"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import type { UIMessage } from "@tanstack/ai-client";

export interface ConversationMeta {
  id: string;
  title: string;
  updatedAt: Date;
  messageCount: number;
}

const INITIAL_ID = "scratch";

function makeThreadId(): string {
  return `thread-${Date.now().toString(36)}`;
}

export function useConversations() {
  const [meta, setMeta] = useState<Record<string, ConversationMeta>>({});
  const [activeId, setActiveId] = useState(INITIAL_ID);
  const counters = useRef<Record<string, number>>({});
  const [threadMessages, setThreadMessages] = useState<Record<string, UIMessage[]>>({});

  const activeIdResolved = activeId || INITIAL_ID;

  const threads = useMemo(
    () => Object.values(meta).sort((a, b) => b.updatedAt.getTime() - a.updatedAt.getTime()),
    [meta],
  );

  /** Stamp a title on the active thread (first question wins). */
  const ensureThread = useCallback((id: string, prompt: string) => {
    const title = prompt.trim().slice(0, 64) || "Untitled thread";
    setMeta((prev) => ({
      ...prev,
      [id]: {
        ...prev[id],
        id,
        title: prev[id]?.title || title,
        updatedAt: new Date(),
        messageCount: prev[id]?.messageCount ?? 0,
      },
    }));
  }, []);

  /** Sync the live message list for a thread back into the store. */
  const syncMessages = useCallback((id: string, messages: UIMessage[]) => {
    setThreadMessages((prev) => (prev[id] === messages ? prev : { ...prev, [id]: messages }));
    const count = messages.length;
    if (counters.current[id] !== count) {
      counters.current[id] = count;
      setMeta((prev) => (prev[id] ? { ...prev, [id]: { ...prev[id], messageCount: count } } : prev));
    }
  }, []);

  const removeThread = useCallback(
    (id: string) => {
      setMeta((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      setThreadMessages((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      if (activeIdResolved === id) setActiveId(INITIAL_ID);
    },
    [activeIdResolved],
  );

  const setActive = useCallback((id: string) => setActiveId(id), []);
  const startNew = useCallback(() => setActiveId(makeThreadId()), []);

  return {
    threads,
    activeThreadId: activeIdResolved,
    threadMessages,
    setActiveThread: setActive,
    ensureThread,
    removeThread,
    startNew,
    syncMessages,
  };
}
