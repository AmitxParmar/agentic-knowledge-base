/**
 * features/research/components/research-workspace.tsx
 * ---------------------------------------------------
 * Purpose:    Orchestrates the research loop — conversation rail on the
 *             left, working pane on the right. The chat thread is the single
 *             surface for progress (inline thinking trace), answer, and
 *             sources; ingestion lives in a collapsible panel above it.
 * Dependencies: conversation-sidebar, upload-composer, research-chat
 * Scope:      /research page body.
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import { ConversationSidebar } from "./conversation-sidebar";
import { UploadComposer } from "./upload-composer";
import { ResearchChat } from "./research-chat";
import { useConversations } from "../api/use-conversations";
import { useResearchRun, type RunEvent } from "../api/use-research-run";
import { searchableDocumentsExist } from "../research-service";

export function ResearchWorkspace() {
  const [ready, setReady] = useState(false);
  const [showUpload, setShowUpload] = useState(true);
  const {
    threads,
    activeThreadId,
    threadMessages,
    setActiveThread,
    ensureThread,
    removeThread,
    startNew,
    syncMessages,
    linkRun,
  } = useConversations();

  // Hydrate readiness from server state: if the workspace already has
  // searchable documents, skip the upload gate on mount. Failures fall back
  // to the cold-start behavior (show upload, not ready).
  useEffect(() => {
    let cancelled = false;
    searchableDocumentsExist()
      .then((exists) => {
        if (cancelled) return;
        if (exists) {
          setReady(true);
          setShowUpload(false);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // Citation metadata flows from the research run into the chat thread so
  // [n] markers resolve to source references. Progress stages display inline
  // in the active answer while a run is streaming. Run state is driven by the
  // chat SSE stream (stages / citations / RUN_FINISHED / RUN_ERROR) — the
  // single execution path, no WebSocket.
  const { state: runState, beginRun, applyEvent, reset } = useResearchRun();

  // Run state (citations/stages/status) belongs to one run in one thread.
  // Dropping it on thread switch keeps restored history from rendering
  // another run's sources panel or resolving its [n] markers against
  // foreign citations.
  useEffect(() => {
    reset();
  }, [activeThreadId, reset]);

  const handleQuestion = useCallback(
    (prompt: string) => {
      ensureThread(activeThreadId, prompt);
      beginRun();
    },
    [activeThreadId, ensureThread, beginRun],
  );

  const handleRunEvent = useCallback(
    (event: RunEvent) => {
      applyEvent(event);
      // Link the completed run to the active thread for server-side history.
      if (event.type === "RUN_FINISHED" && event.runId) {
        linkRun(activeThreadId, event.runId);
      }
    },
    [applyEvent, activeThreadId, linkRun],
  );

  const toggleUpload = useCallback(() => setShowUpload((v) => !v), []);

  return (
    <main className="flex h-[calc(100vh-52px)] min-h-0">
      {/* rail */}
      <div className="flex w-64 shrink-0 flex-col border-r border-line bg-inset/60">
        <ConversationSidebar
          threads={threads}
          activeId={activeThreadId}
          onSelect={setActiveThread}
          onDelete={removeThread}
        />
        <button
          type="button"
          onClick={startNew}
          className="mx-2 mb-3 flex h-9 items-center gap-1.5 rounded-control px-2.5 text-[13px] font-medium text-ink transition-colors duration-150 hover:bg-hover-2"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New research
        </button>
      </div>

      {/* work pane */}
      <section className="flex min-h-0 flex-1 flex-col px-4 pt-2">
        <div className="flex items-center px-2 pb-1">
          <button
            type="button"
            onClick={toggleUpload}
            aria-expanded={showUpload}
            className="flex h-7 items-center gap-1.5 rounded-control px-2 text-[12px] text-ink-3 transition-colors duration-150 hover:bg-hover hover:text-ink"
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={showUpload ? "transition-transform duration-200 rotate-90" : "transition-transform duration-200"}
              aria-hidden="true"
            >
              <path d="M9 6l6 6-6 6" />
            </svg>
            Ingest source
          </button>
          {!ready && (
            <span className="ml-2 rounded-full bg-orange/15 px-2 py-0.5 text-[11px] font-medium text-orange">
              Ingest a document before asking
            </span>
          )}
        </div>

        {showUpload && (
          <div className="mb-3">
            <UploadComposer
              onIngestionComplete={() => {
                setReady(true);
                setShowUpload(false);
              }}
            />
          </div>
        )}

        <ResearchChat
          key={activeThreadId}
          threadId={activeThreadId}
          initialMessages={threadMessages[activeThreadId] ?? []}
          citations={runState.citations}
          stages={runState.stages}
          runStatus={runState.status}
          runError={runState.error}
          disabled={!ready}
          onQuestion={handleQuestion}
          onRunEvent={handleRunEvent}
          onMessagesChange={(msgs) => syncMessages(activeThreadId, msgs)}
          onToggleUpload={toggleUpload}
        />
      </section>
    </main>
  );
}
