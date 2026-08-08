/**
 * features/research/components/research-chat.tsx
 * ----------------------------------------------
 * Purpose:    Perplexity-style conversation thread — one Q/A row per message,
 *             inline citations in the answer, sticky composer at the bottom.
 *             Owns thread hydration (initialMessages) and syncs its live
 *             message list back to the conversation store so thread switching
 *             restores history. Renders an inline progress-stage strip while
 *             a research run is streaming.
 * Dependencies: api/use-research-chat.ts, citation-ref.tsx, progress-stage-list
 * Scope:      Research page conversation surface.
 */

"use client";

import { useEffect, useRef, useState } from "react";
import { useResearchChat } from "../api/use-research-chat";
import { CitationRef } from "./citation-ref";
import { ProgressStageList } from "./progress-stage-list";
import { groupCitations, type GroupedCitation } from "../utils/parse-citations";
import type { Citation } from "../utils/ws-adapter";
import type { UIMessage } from "@tanstack/ai-client";
import styles from "./research-chat.module.css";

/** Canonical research stages (docs/ux.md). Order = pipeline order. */
const RESEARCH_STAGES = [
  "Searching documents...",
  "Reviewing evidence...",
  "Generating report...",
  "Finalizing answer...",
];

function renderTextWithCitations(text: string, citations: GroupedCitation[]) {
  const parts = text.split(/(\[\d+\])/g);
  return parts.map((segment, index) => {
    const match = segment.match(/^\[(\d+)\]$/);
    if (match?.[1]) {
      const idx = parseInt(match[1], 10);
      const citation = citations.find((c) => c.index === idx);
      if (citation?.chunkId && citation.sourceRef) {
        return (
          <CitationRef
            key={index}
            index={citation.index}
            chunkId={citation.chunkId}
            sourceRef={citation.sourceRef}
            relevanceScore={citation.relevanceScore}
          />
        );
      }
      return <span key={index}>{segment}</span>;
    }
    return <span key={index}>{segment}</span>;
  });
}

export function ResearchChat({
  threadId,
  initialMessages,
  citations,
  stages,
  runStatus,
  disabled,
  onQuestion,
  onMessagesChange,
}: {
  threadId: string;
  initialMessages: UIMessage[];
  citations: Citation[];
  stages: string[];
  runStatus: "idle" | "connecting" | "running" | "complete" | "error";
  disabled: boolean;
  onQuestion: (prompt: string) => void;
  onMessagesChange: (messages: UIMessage[]) => void;
}) {
  const { messages, sendMessage, isLoading, error, stop, clear } = useResearchChat(threadId, initialMessages);
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const grouped = groupCitations(citations);

  // Keep the scroll pinned to the newest message.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Sync the live message list to the conversation store so switching away
  // and back restores this thread's history.
  useEffect(() => {
    onMessagesChange(messages);
  }, [messages, onMessagesChange]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isLoading || disabled) return;
    setInput("");
    onQuestion(trimmed);
    await sendMessage(trimmed);
  }

  // Map the research run's accumulated stages to pending/active/complete.
  const stageStates = RESEARCH_STAGES.map((label, idx) => {
    const reached = stages.indexOf(label);
    let status: "pending" | "active" | "complete" = "pending";
    if (reached !== -1) status = idx === stages.length - 1 && runStatus === "running" ? "active" : "complete";
    return { stage: label, status } as const;
  });
  const showStages = runStatus === "running" || runStatus === "connecting";

  return (
    <section className={styles.chat} aria-label="Research conversation">
      <div className={styles.chatPane}>
        <div className={styles.header}>
          <span className={styles.title}>[ THREAD / {threadId.toUpperCase()} ]</span>
          <div className={styles.headerActions}>
            {isLoading && (
              <button type="button" className={styles.headerBtn} onClick={stop} aria-label="Stop generation">
                Stop
              </button>
            )}
            <button type="button" className={styles.headerBtn} onClick={clear} disabled={messages.length === 0}>
              Clear
            </button>
          </div>
        </div>

        <div className={styles.scroll}>
          <div className={styles.thread} role="log" aria-live="polite">
            {messages.length === 0 && (
              <div className={styles.emptyState}>
                <p className={styles.emptyTitle}>[ READY ]</p>
                <p className={styles.emptyHint}>Ingest a document, then ask. Answers cite their sources inline.</p>
              </div>
            )}

            {messages.map((message) => (
              <div key={message.id} className={`${styles.msg} ${styles[message.role]}`}>
                <span className={styles.role}>
                  {message.role === "user" ? "< QUERY >" : "<< ANSWER >>"}
                </span>

                <div className={styles.bubble}>
                  {message.parts.map((part, index) => {
                    if (part.type === "text" && typeof part.content === "string") {
                      return (
                        <span key={index} className={styles.text}>
                          {renderTextWithCitations(part.content, grouped)}
                        </span>
                      );
                    }
                    if (part.type === "tool-call") {
                      return (
                        <span key={index} className={styles.toolCall}>
                          [ {part.name?.toUpperCase() ?? "TOOL RESULT"} ]
                        </span>
                      );
                    }
                    return null;
                  })}

                  {message.role === "assistant" && isLoading && message === messages[messages.length - 1] && (
                    <span className={styles.typing}>
                      <span className={styles.dot} />
                      <span className={styles.dot} />
                      <span className={styles.dot} />
                    </span>
                  )}
                </div>
              </div>
            ))}

            <div ref={messagesEndRef} />
          </div>

          {error && (
            <p className={styles.error} role="alert">
              {error.message}
            </p>
          )}
        </div>

        {showStages && (
          <div className={styles.progressStrip}>
            <ProgressStageList stages={stageStates} />
          </div>
        )}

        <form className={styles.composer} onSubmit={handleSubmit}>
          <label className="visually-hidden" htmlFor="chat-input">
            Ask a question
          </label>
          <input
            id="chat-input"
            className={styles.input}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={disabled ? "Ingest a source first…" : "Ask about the evidence…"}
            disabled={disabled}
          />
          <button type="submit" className={styles.sendBtn} disabled={disabled || isLoading || !input.trim()}>
            {isLoading ? "…" : ">>> RUN"}
          </button>
        </form>
      </div>
    </section>
  );
}
