/**
 * features/research/api/use-conversations.ts
 * ------------------------------------------
 * Purpose:    Conversation thread store. Thread metadata (id/title) is
 *             server-backed via /api/conversations; the live message list is
 *             still held in memory keyed by threadId. On mount, the store
 *             fetches the workspace's threads; creating/renaming/deleting hits
 *             the API. The per-thread message shape matches TanStack AI's
 *             UIMessage so thread-switching restores history.
 * Dependencies: react, conversation-client
 * Scope:      Research chat conversation history.
 */

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { UIMessage } from "@tanstack/ai-client";
import {
  deleteThread,
  linkRun as linkRunApi,
  listThreads,
  type ThreadSummary,
} from "./conversation-client";

export interface ConversationMeta {
  id: string;
  title: string;
  updatedAt: Date;
  messageCount: number;
}

const INITIAL_ID = "scratch";

export function useConversations() {
  const [meta, setMeta] = useState<Record<string, ConversationMeta>>({});
  const [activeId, setActiveId] = useState(INITIAL_ID);
  const [loaded, setLoaded] = useState(false);
  const counters = useRef<Record<string, number>>({});
  const [threadMessages, setThreadMessages] = useState<Record<string, UIMessage[]>>({});

  const activeIdResolved = activeId || INITIAL_ID;

  const threads = useMemo(
    () => Object.values(meta).sort((a, b) => b.updatedAt.getTime() - a.updatedAt.getTime()),
    [meta],
  );

  // Hydrate threads from the server on first mount.
  useEffect(() => {
    let cancelled = false;
    listThreads()
      .then((data) => {
        if (cancelled) return;
        setMeta(toMetaRecord(data.threads));
      })
      .catch((err) => console.warn("[conversations] load failed:", err))
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const refresh = useCallback(() => {
    return listThreads().then((data) => setMeta(toMetaRecord(data.threads)));
  }, []);

  /** Stamp a title on the active thread locally; the first question wins. */
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
      deleteThread(id).catch((err) => console.warn("[conversations] delete failed:", err));
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
  const startNew = useCallback(() => setActiveId(INITIAL_ID), []);

  const linkRun = useCallback(
    (threadId: string, runId: string) => {
      // Only server-backed threads (real UUIDs) can be linked; skip scratch.
      if (threadId === INITIAL_ID) return;
      linkRunApi(threadId, runId)
        .then((updated) =>
          setMeta((prev) =>
            prev[threadId] ? { ...prev, [threadId]: { ...prev[threadId], title: updated.title } } : prev,
          ),
        )
        .catch((err) => console.warn("[conversations] link run failed:", err));
    },
    [],
  );

  return {
    threads,
    activeThreadId: activeIdResolved,
    threadMessages,
    loaded,
    setActiveThread: setActive,
    ensureThread,
    removeThread,
    startNew,
    syncMessages,
    refresh,
    linkRun,
  };
}

function toMetaRecord(threads: ThreadSummary[]): Record<string, ConversationMeta> {
  const next: Record<string, ConversationMeta> = {};
  for (const t of threads) {
    next[t.id] = {
      id: t.id,
      title: t.title,
      updatedAt: new Date(t.updated_at),
      messageCount: t.run_count,
    };
  }
  return next;
}
