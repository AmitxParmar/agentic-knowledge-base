/**
 * features/research/components/research-chat.tsx
 * ----------------------------------------------
 * Purpose:    TanStack AI-powered chat UI for the research page.
 *             Renders messages, progress streaming, answer text, and
 *             client tool buttons (copy/clear).
 * Dependencies: api/use-research-chat.ts, research-chat.module.css
 * Scope:      Research page chat column.
 */

"use client";

import { useState, type FormEvent } from "react";
import { useResearchChat } from "../api/use-research-chat";
import styles from "./research-chat.module.css";

interface ResearchChatProps {
  disabled: boolean;
  onQuestion: (question: string) => void;
}

export function ResearchChat({ disabled, onQuestion }: ResearchChatProps) {
  const { messages, sendMessage, isLoading, error, stop, clear } = useResearchChat();
  const [input, setInput] = useState("");

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
          <p className={styles.progressText}>
            Ask a question about your uploaded documents.
          </p>
        )}
        {messages.map((message) => (
          <div key={message.id} className={`${styles.message} ${styles[message.role]}`}>
            {message.parts.map((part, idx) => {
              if (part.type === "text") {
                return (
                  <span key={idx} className={styles.bubble}>
                    {part.content}
                  </span>
                );
              }
              return null;
            })}
          </div>
        ))}
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
          {isLoading ? "…" : "Ask"}
        </button>
      </form>
    </div>
  );
}
