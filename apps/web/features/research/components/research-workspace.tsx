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

  return (
    <div className="flex flex-1 min-h-0 w-full overflow-hidden">
      {/* rail */}
      <aside className="flex w-64 shrink-0 flex-col border-r border-line bg-inset/50 min-h-0 overflow-hidden">
        <ConversationSidebar
          threads={threads}
          activeId={activeThreadId}
          onSelect={setActiveThread}
          onDelete={removeThread}
          onNew={startNew}
        />
      </aside>

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
        />
      </main>
    </div>
  );
}
