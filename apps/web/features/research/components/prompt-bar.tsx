/**
 * features/research/components/prompt-bar.tsx
 * -------------------------------------------
 * Purpose:    Perplexity-style composer — auto-growing textarea over a
 *             control row: attach (opens the ingestion panel), model badge,
 *             voice mic, and a send/stop action. Enter sends, Shift+Enter
 *             adds a newline.
 * Dependencies: voice-button.tsx (ADR-009 styling)
 * Scope:      Research chat composer.
 */

"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { VoiceButton } from "./voice-button";

interface PromptBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  /** A run is streaming — send becomes stop. */
  busy?: boolean;
  /** Workspace gate: no searchable documents yet. */
  disabled?: boolean;
  placeholder?: string;
  modelLabel?: string | null;
  onAttachClick?: () => void;
}

function IconButton({
  label,
  onClick,
  disabled,
  active,
  children,
}: {
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  active?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={active}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-control",
        "text-ink-3 transition-[background-color,color,transform] duration-150",
        "enabled:hover:bg-hover enabled:hover:text-ink enabled:active:scale-[0.94]",
        "disabled:cursor-not-allowed disabled:opacity-40",
        active && "bg-accent-tint !text-accent-ink",
      )}
    >
      {children}
    </button>
  );
}

export function PromptBar({
  value,
  onChange,
  onSubmit,
  onStop,
  busy = false,
  disabled = false,
  placeholder = "Ask about your documents…",
  modelLabel,
  onAttachClick,
}: PromptBarProps) {
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Grow with content up to a compact maximum, then scroll internally.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "0px";
    const content = el.scrollHeight;
    el.style.height = `${Math.min(Math.max(content, 22), 120)}px`;
    el.style.overflowY = content > 120 ? "auto" : "hidden";
  }, [value]);

  const canSend = !busy && !disabled && value.trim().length > 0;

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (canSend) onSubmit();
    }
  }

  return (
    <div className="rounded-card border border-line bg-surface shadow-card transition-colors duration-150 focus-within:border-line-strong">
      <label className="sr-only" htmlFor="prompt-input">
        Ask a question
      </label>
      <textarea
        id="prompt-input"
        ref={inputRef}
        rows={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={disabled ? "Ingest a source first…" : placeholder}
        disabled={disabled}
        className="block max-h-[120px] w-full resize-none bg-transparent px-3.5 pb-1 pt-3 text-[14px] leading-[22px] text-ink outline-none [overflow-wrap:anywhere] placeholder:text-ink-3 disabled:cursor-not-allowed"
      />

      <div className="flex items-center gap-0.5 px-1.5 pb-1.5 pt-1">
        <IconButton label="Ingest a document" onClick={onAttachClick} disabled={busy}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </IconButton>

        {modelLabel && (
          <span
            className="ml-1 hidden h-7 select-none items-center gap-1.5 rounded-chip bg-inset px-2 text-[12px] font-medium text-ink-2 shadow-btn sm:inline-flex"
            title="Active research model"
          >
            <span className="size-1.5 rounded-full bg-green" aria-hidden="true" />
            {modelLabel}
          </span>
        )}

        <span className="min-w-2 flex-1" />

        <VoiceButton disabled={disabled} compact />

        {busy ? (
          <IconButton label="Stop generating" onClick={onStop}>
            <span className="size-2.5 rounded-[2px] bg-current" aria-hidden="true" />
          </IconButton>
        ) : (
          <button
            type="button"
            aria-label="Send question"
            title="Send (Enter)"
            disabled={!canSend}
            onClick={onSubmit}
            className={cn(
              "flex size-8 shrink-0 items-center justify-center rounded-control transition-[background-color,color,transform] duration-200",
              "enabled:active:scale-[0.94]",
              canSend ? "bg-ink text-page" : "cursor-not-allowed bg-line-strong text-ink-2 opacity-60",
            )}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}
