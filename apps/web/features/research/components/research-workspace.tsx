/**
 * features/research/components/research-workspace.tsx
 * ---------------------------------------------------
 * Purpose:    Orchestrates the research loop in a Perplexity-style layout —
 *             conversation rail on the left, working pane on the right. The
 *             chat thread is the single surface for progress + answer + sources
 *             (citation-backed); the upload is a compact panel for ingestion.
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
import styles from "./research-workspace.module.css";

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
  const { state: runState, beginRun, applyEvent } = useResearchRun();

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

  return (
    <main className={styles.workspace}>
      <aside className={styles.rail}>
        <ConversationSidebar
          threads={threads}
          activeId={activeThreadId}
          onSelect={setActiveThread}
          onDelete={removeThread}
        />
        <div className={styles.railActions}>
          <button type="button" className={styles.newThread} onClick={startNew}>
            [ + New research ]
          </button>
        </div>
      </aside>

      <section className={styles.work}>
        <div className={styles.workHeader}>
          <h1 className={styles.workTitle}>Research Terminal</h1>
          <span className={styles.workMeta}>
            CITATIONS / {runState.citations.length} SRC /{" "}
            {runState.runId?.slice(0, 8).toUpperCase() ?? "—"}
          </span>
        </div>

        <div className={styles.uploadRow}>
          <button
            type="button"
            className={styles.uploadToggle}
            onClick={() => setShowUpload((v) => !v)}
            aria-expanded={showUpload}
          >
            {showUpload ? "▴ Hide ingestion" : "▾ Ingest source"}
          </button>
          {!ready ? (
            <span className={styles.gate}>[ WAIT ] Ingest a document before asking</span>
          ) : (
            <span className={styles.gateReady}>[ READY ]</span>
          )}
        </div>

        {showUpload && (
          <UploadComposer
            onIngestionComplete={() => {
              setReady(true);
              setShowUpload(false);
            }}
          />
        )}

        <ResearchChat
          key={activeThreadId}
          threadId={activeThreadId}
          initialMessages={threadMessages[activeThreadId] ?? []}
          citations={runState.citations}
          stages={runState.stages}
          runStatus={runState.status}
          disabled={!ready}
          onQuestion={handleQuestion}
          onRunEvent={handleRunEvent}
          onMessagesChange={(msgs) => syncMessages(activeThreadId, msgs)}
        />
      </section>
    </main>
  );
}
