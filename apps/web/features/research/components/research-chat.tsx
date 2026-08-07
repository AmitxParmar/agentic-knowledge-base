/**
 * features/research/components/research-chat.tsx
 * ----------------------------------------------
 * Purpose:    TanStack AI-powered chat UI for the research page.
 *             Renders messages, progress streaming, answer text,
 *             tool call results, and client tool buttons (copy/clear).
 * Dependencies: api/use-research-chat.ts, api/use-auto-scroll.ts,
 *               research-chat.module.css
 * Scope:      Research page chat column.
 */

"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useResearchChat } from "../api/use-research-chat";
import { CitationRef } from "./citation-ref";
import { groupCitations } from "../utils/parse-citations";
import styles from "./research-chat.module.css";

interface ResearchChatProps {
  disabled: boolean;
  onQuestion: (question: string) => void;
}

function MessagePart({ part, citations }: { part: { type: string; content?: string | Array<{ type: string }>; name?: string; output?: unknown; state?: string }; citations: ReturnType<typeof groupCitations> }) {
  if (part.type === "text" && typeof part.content === "string") {
    const textContent = part.content;
    const parts = textContent.split(/(\[\d+\])/g);
    return (
      <span className={styles.bubble}>
        {parts.map((segment, idx) => {
          const match = segment.match(/^\[(\d+)\]$/);
          if (match && match[1]) {
            const citationIndex = parseInt(match[1], 10);
            const citation = citations.find((c) => c.index === citationIndex);
            if (citation && citation.chunkId && citation.sourceRef) {
              return (
                <CitationRef
                  key={idx}
                  index={citation.index}
                  chunkId={citation.chunkId}
                  sourceRef={citation.sourceRef}
                  relevanceScore={citation.relevanceScore}
                />
              );
            }
          }
          return <span key={idx}>{segment}</span>;
        })}
      </span>
    );
  }

  if (part.type === "tool-call") {
    return (
      <span className={styles.toolCall}>
        {part.name === "copyAnswer"
          ? "Copied to clipboard"
          : part.name === "clearHistory"
            ? "History cleared"
            : `Tool: ${part.name}`}
      </span>
    );
  }

  return null;
}

export function ResearchChat({ disabled, onQuestion }: ResearchChatProps) {
  const { messages, sendMessage, isLoading, error, stop, clear } = useResearchChat();
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isLoading || disabled) return;
    setInput("");
    onQuestion(trimmed);
    await sendMessage(trimmed);
  }

  return (
    <div className={styles.chat}>
      <div className={styles.header}>
        <h2 className={styles.title}>Research Chat</h2>
        <div className={styles.toolbar}>
          <button
            type="button"
            className={styles.toolbarButton}
            onClick={clear}
            disabled={messages.length === 0}
          >
            Clear
          </button>
          {isLoading && (
            <button type="button" className={styles.toolbarButton} onClick={stop}>
              Stop
            </button>
          )}
        </div>
      </div>

      <div className={styles.messages} role="log" aria-live="polite">
        {messages.length === 0 && (
          <div className={styles.emptyState}>
            <p className={styles.emptyTitle}>Ready to research</p>
            <p className={styles.emptyHint}>
              Upload a document, then ask a question. I&apos;ll find evidence and cite my sources.
            </p>
          </div>
        )}

        {messages.map((message) => (
          <div key={message.id} className={`${styles.message} ${styles[message.role]}`}>
            <span className={styles.roleLabel}>
              {message.role === "user" ? "You" : "Assistant"}
            </span>
            {message.parts.map((part, idx) => (
              <MessagePart key={idx} part={part} citations={[]} />
            ))}
          </div>
        ))}

        {isLoading && messages.length > 0 && (
          <div className={`${styles.message} ${styles.assistant}`}>
            <span className={styles.roleLabel}>Assistant</span>
            <span className={styles.typingIndicator}>
              <span className={styles.dot} />
              <span className={styles.dot} />
              <span className={styles.dot} />
            </span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {error && (
        <p className={styles.error} role="alert">
          {error.message}
        </p>
      )}

      <form className={styles.inputRow} onSubmit={handleSubmit}>
        <label className="visually-hidden" htmlFor="chat-input">
          Your question
        </label>
        <input
          id="chat-input"
          className={styles.input}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder={disabled ? "Upload and ingest a document first…" : "Ask a question…"}
          disabled={disabled}
        />
        <button type="submit" className={styles.sendButton} disabled={disabled || isLoading}>
          {isLoading ? "Asking…" : "Ask"}
        </button>
      </form>
    </div>
  );
}
