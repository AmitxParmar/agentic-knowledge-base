/**
 * features/research/components/question-composer.tsx
 * --------------------------------------------------
 * Purpose:    Question input + submit. Disabled until ingestion is complete.
 * Dependencies: question-composer.module.css
 * Scope:      Research page question section.
 */

"use client";

import { useState, type FormEvent } from "react";
import styles from "./question-composer.module.css";

interface QuestionComposerProps {
  disabled: boolean;
  onSubmit: (question: string) => void;
}

const MAX_LENGTH = 1000;

export function QuestionComposer({ disabled, onSubmit }: QuestionComposerProps) {
  const [question, setQuestion] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) {
      setLocalError("Enter a question before asking.");
      return;
    }
    setLocalError(null);
    onSubmit(trimmed);
    setQuestion("");
  }

  const isDisabled = disabled;

  return (
    <form className={styles.composer} onSubmit={handleSubmit}>
      <div className={styles.header}>
        <h2 className={styles.title}>2. Ask A Question</h2>
        <span className={`${styles.badge} ${!disabled ? styles.badgeReady : ""}`}>
          {disabled ? "waiting" : "ready"}
        </span>
      </div>

      <label className="visually-hidden" htmlFor="question-input">
        Your question
      </label>
      <textarea
        id="question-input"
        className={styles.textarea}
        value={question}
        onChange={(event) => {
          setQuestion(event.target.value);
          setLocalError(null);
        }}
        placeholder="What does this document say about...?"
        maxLength={MAX_LENGTH}
        disabled={isDisabled}
        aria-describedby="char-hint"
      />

      <div className={styles.footer}>
        <span id="char-hint" className={styles.charHint}>
          {question.length}/{MAX_LENGTH}
        </span>
        <button type="submit" className={styles.submit} disabled={isDisabled}>
          Run research
        </button>
      </div>

      {localError && <p className={styles.error}>{localError}</p>}
    </form>
  );
}
