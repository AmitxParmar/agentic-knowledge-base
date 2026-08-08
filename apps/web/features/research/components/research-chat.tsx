/**
 * features/research/components/research-chat.tsx
 * ----------------------------------------------
 * Purpose:    Perplexity-style conversation thread — one Q/A row per message,
 *             inline citations in the answer, sticky composer at the bottom,
 *             right-rail history (thread binding) for multi-session continuity.
 * Dependencies: api/use-research-chat.ts, conversation-sidebar,
 *               citation-ref.tsx, conversation state
 * Scope:      Research page conversation surface.
 */

"use client";

import { useEffect, useRef, useState } from "react";
import { useResearchChat } from "../api/use-research-chat";
import { CitationRef } from "./citation-ref";
import { groupCitations, type GroupedCitation } from "../utils/parse-citations";
import type { Citation } from "../utils/ws-adapter";
import styles from "./research-chat.module.css";

/**
 * Split text into segments and render [n] as citation refs.
 */
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
  disabled,
  threadId,
  citations,
  onQuestion,
}: {
  disabled: boolean;
  threadId: string;
  citations: Citation[];
  onQuestion: (prompt: string) => void;
}) {
  const { messages, sendMessage, isLoading, error, stop, clear } = useResearchChat(threadId);
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Group once per render — citation metadata (chunk_id/source_ref/score) is
  // the shared source of truth for every [n] marker in the whole thread.
  const grouped = groupCitations(citations);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isLoading || disabled) return;
    setInput("");
    onQuestion(trimmed);
    await sendMessage(trimmed);
  }

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

                  {message.role === "assistant" && isLoading && messages.length === 1 && (
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
          <button
            type="submit"
            className={styles.sendBtn}
            disabled={disabled || isLoading || !input.trim()}
          >
            {isLoading ? "…" : ">>> RUN"}
          </button>
        </form>
      </div>
    </section>
  );
}
