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
  const [checkingReady, setCheckingReady] = useState(true);
  const [showUpload, setShowUpload] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
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
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setCheckingReady(false);
      });
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

  const handleSelectThread = useCallback(
    (id: string) => {
      setActiveThread(id);
      setSidebarOpen(false);
    },
    [setActiveThread],
  );

  const handleNewThread = useCallback(() => {
    startNew();
    setSidebarOpen(false);
  }, [startNew]);

  return (
    <div className="flex flex-1 min-h-0 w-full overflow-hidden">
      {/* desktop rail — hidden on mobile */}
      <aside className="hidden md:flex w-64 shrink-0 flex-col border-r border-line bg-inset/50 min-h-0 overflow-hidden">
        <ConversationSidebar
          threads={threads}
          activeId={activeThreadId}
          onSelect={setActiveThread}
          onDelete={removeThread}
          onNew={startNew}
        />
      </aside>

      {/* mobile drawer */}
      {sidebarOpen && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[1px] md:hidden"
            onClick={() => setSidebarOpen(false)}
            aria-hidden="true"
          />
          <aside className="fixed inset-y-0 left-0 z-50 flex w-[84%] max-w-[300px] flex-col border-r border-line bg-inset shadow-raised md:hidden overflow-hidden">
            <div className="flex items-center justify-between px-3.5 py-2.5 border-b border-line/40 shrink-0">
              <div className="flex items-center gap-2">
                <span className="text-[11.5px] font-semibold uppercase tracking-wider text-ink-3">History</span>
                <span className="rounded-full bg-inset px-2 py-0.5 text-[11px] font-medium text-ink-3 tabular-nums shadow-hairline">
                  {threads.length}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={handleNewThread}
                  className="flex h-7 items-center gap-1 rounded-control bg-surface-raised px-2.5 text-[12px] font-medium text-ink transition-colors duration-150 hover:bg-hover hover:text-accent shadow-btn"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true">
                    <path d="M12 5v14M5 12h14" />
                  </svg>
                  <span>New</span>
                </button>
                <button
                  type="button"
                  onClick={() => setSidebarOpen(false)}
                  aria-label="Close history"
                  className="flex size-7 items-center justify-center rounded-control text-ink-3 hover:bg-hover hover:text-ink"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
                    <path d="M18 6L6 18M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>
            <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
              <ConversationSidebar
                threads={threads}
                activeId={activeThreadId}
                onSelect={handleSelectThread}
                onDelete={removeThread}
                onNew={handleNewThread}
                hideHeader
              />
            </div>
          </aside>
        </>
      )}

      {/* work pane */}
      <main className="flex min-h-0 flex-1 flex-col overflow-hidden bg-page">
        {showUpload && (
          <div className="p-4 border-b border-line/30 bg-inset/20 shrink-0">
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
          disabled={checkingReady ? false : !ready}
          isCheckingReady={checkingReady}
          onQuestion={handleQuestion}
          onRunEvent={handleRunEvent}
          onMessagesChange={(msgs) => syncMessages(activeThreadId, msgs)}
          onToggleUpload={toggleUpload}
          showUpload={showUpload}
          onOpenHistory={() => setSidebarOpen(true)}
        />
      </main>
    </div>
  );
}
