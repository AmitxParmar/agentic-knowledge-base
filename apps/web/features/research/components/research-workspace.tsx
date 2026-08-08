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

import { useCallback, useState } from "react";
import { ConversationSidebar } from "./conversation-sidebar";
import { UploadComposer } from "./upload-composer";
import { ResearchChat } from "./research-chat";
import { useConversations } from "../api/use-conversations";
import { useResearchRun } from "../api/use-research-run";
import styles from "./research-workspace.module.css";

export function ResearchWorkspace() {
  const [ready, setReady] = useState(false);
  const [showUpload, setShowUpload] = useState(true);
  const { threads, activeThreadId, setActiveThread, ensureThread, removeThread, startNew } =
    useConversations();

  // Citation metadata flows from the research run into the chat thread so
  // [n] markers resolve to source references. Answer text streams via SSE chat.
  const { state: runState, startResearch } = useResearchRun();

  const handleQuestion = useCallback(
    (prompt: string) => {
      const id = ensureThread(prompt);
      startResearch(prompt);
      setActiveThread(id === "scratch" ? "scratch" : id);
    },
    [ensureThread, setActiveThread, startResearch],
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
            CITATIONS / {runState.citations.length} SRC / {runState.runId?.slice(0, 8).toUpperCase() ?? "—"}
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
          disabled={!ready}
          threadId="research-main"
          citations={runState.citations}
          onQuestion={handleQuestion}
        />
      </section>
    </main>
  );
}
