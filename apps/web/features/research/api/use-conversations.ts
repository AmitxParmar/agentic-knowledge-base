"use client";

import { useCallback, useMemo, useRef, useState } from "react";

export interface ConversationMeta {
  id: string;
  title: string;
  updatedAt: Date;
  messageCount: number;
}

export function useConversations() {
  const [meta, setMeta] = useState<Record<string, ConversationMeta>>({});
  const [activeId, setActiveId] = useState("scratch");
  const counters = useRef<Record<string, number>>({});

  const activeIdResolved = activeId || "scratch";

  const threads = useMemo(
    () => Object.values(meta).sort((a, b) => b.updatedAt.getTime() - a.updatedAt.getTime()),
    [meta],
  );

  const makeThreadId = useCallback(() => `thread-${Date.now().toString(36)}`, []);

  /** Create or reuse a thread for the current prompt and increment its message count. */
  const ensureThread = useCallback(
    (prompt: string) => {
      const title = prompt.trim().slice(0, 64) || "New thread";
      const id = activeIdResolved === "scratch" ? makeThreadId() : activeIdResolved;
      counters.current[id] = (counters.current[id] ?? 0) + 1;
      setMeta((prev) => ({
        ...prev,
        [id]: {
          ...prev[id],
          id,
          title: prev[id]?.title || title,
          updatedAt: new Date(),
          messageCount: (counters.current[id] ?? 1),
        },
      }));
      return id;
    },
    [activeIdResolved, makeThreadId],
  );

  const setActive = useCallback((id: string) => setActiveId(id), []);
  const startNew = useCallback(() => setActiveId("scratch"), []);
  const removeThread = useCallback(
    (id: string) => {
      setMeta((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      if (activeIdResolved === id) setActiveId("scratch");
    },
    [activeIdResolved],
  );

  return {
    threads,
    activeThreadId: activeIdResolved,
    setActiveThread: setActive,
    ensureThread,
    removeThread,
    startNew,
    currentThreadId: "research-main",
  };
}
