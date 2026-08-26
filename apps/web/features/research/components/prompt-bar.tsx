/**
 * features/research/components/prompt-bar.tsx
 * -------------------------------------------
 * Purpose:    Compact, responsive prompt composer with inline controls:
 *             attach, model badge/picker, voice mic, and send/stop action.
 *             Supports single-line inline layout that smoothly expands into
 *             multi-line when text wraps.
 * Scope:      Research chat composer.
 */

"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { VoiceButton } from "./voice-button";

interface PromptBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  busy?: boolean;
  disabled?: boolean;
  placeholder?: string;
  modelLabel?: string | null;
  onAttachClick?: () => void;
  className?: string;
}

function Icon({
  children,
  size = 15,
  strokeWidth = 1.8,
}: {
  children: React.ReactNode;
  size?: number;
  strokeWidth?: number;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
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
  className,
}: Readonly<PromptBarProps>) {
  const [expanded, setExpanded] = useState(false);
  const wide = expanded;

  const composerAnchorRef = useRef<HTMLDivElement>(null);
  const controlsRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const measureRef = useRef<HTMLSpanElement>(null);
  const modelRef = useRef<HTMLButtonElement>(null);

  // Auto-grow & layout switch (single inline row vs multi-line wide layout)
  useLayoutEffect(() => {
    const input = inputRef.current;
    const controls = controlsRef.current;
    const measure = measureRef.current;
    const modelButton = modelRef.current;
    if (!input || !controls || !measure) return;

    const fixedControlsWidth = 28 * 3 + (modelButton?.offsetWidth ?? 60);
    const inlineGaps = 4 * 4;
    const inlineInputWidth = controls.clientWidth - fixedControlsWidth - inlineGaps;
    const needsFullWidth = value.includes("\n") || measure.offsetWidth + 8 > inlineInputWidth;

    if (needsFullWidth !== expanded) {
      setExpanded(needsFullWidth);
    }

    const minHeight = 28;
    const maxHeight = 120;
    input.style.height = "0px";
    const contentHeight = input.scrollHeight;
    input.style.height = `${Math.min(Math.max(contentHeight, minHeight), maxHeight)}px`;
    input.style.overflowY = contentHeight > maxHeight ? "auto" : "hidden";
  }, [value, expanded]);

  const canSend = !busy && !disabled && value.trim().length > 0;

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (canSend) onSubmit();
    }
  }

  return (
    <div className={cn("w-full", className)}>
      <div ref={composerAnchorRef} className="relative">
        <div
          className={cn(
            "relative isolate flex flex-col overflow-hidden border border-line bg-surface shadow-card transition-[border-color,border-radius] duration-150 focus-within:border-line-strong rounded-[14px] gap-1.5 p-1.5",
          )}
        >
          <span
            ref={measureRef}
            aria-hidden="true"
            className="pointer-events-none absolute invisible whitespace-pre text-[13px] leading-[18px]"
          >
            {value}
          </span>

          <div
            ref={controlsRef}
            className={cn(
              "grid items-end gap-x-1 gap-y-1.5",
              wide
                ? "grid-cols-[28px_auto_minmax(0,1fr)_28px_28px]"
                : "grid-cols-[28px_minmax(0,1fr)_auto_28px_28px]",
            )}
          >
            {/* Attach / Ingest button */}
            <button
              type="button"
              aria-label="Add attachments and sources"
              disabled={busy || disabled}
              onClick={onAttachClick}
              className={cn(
                "flex size-7 shrink-0 items-center justify-center justify-self-start rounded-[8px] text-ink-3 transition-[background-color,color,transform] duration-150 enabled:hover:bg-hover enabled:hover:text-ink enabled:active:scale-[0.94] disabled:opacity-40 disabled:cursor-not-allowed",
                wide ? "col-start-1 row-start-2" : "col-start-1 row-start-1",
              )}
            >
              <Icon size={16} strokeWidth={2}>
                <path d="M12 5v14M5 12h14" />
              </Icon>
            </button>

            {/* Input textarea */}
            <textarea
              id="prompt-input"
              ref={inputRef}
              rows={1}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={disabled ? "Ingest a source first…" : placeholder}
              disabled={disabled}
              aria-label="Prompt"
              className={cn(
                "min-h-7 min-w-0 w-full resize-none bg-transparent px-1 py-[5px] text-[13px] leading-[18px] text-ink outline-none [overflow-wrap:anywhere] placeholder:text-ink-3 disabled:cursor-not-allowed",
                wide ? "col-span-full col-start-1 row-start-1" : "col-start-2 row-start-1",
              )}
            />

            {/* Active Model Badge */}
            {modelLabel && (
              <button
                ref={modelRef}
                type="button"
                aria-label="Active model"
                className={cn(
                  "flex h-7 shrink-0 items-center gap-1.5 rounded-[8px] bg-inset px-2 text-[12px] font-medium text-ink-2 shadow-btn select-none pointer-events-none",
                  wide ? "col-start-2 row-start-2 justify-self-start" : "col-start-3 row-start-1",
                )}
              >
                <span className="size-1.5 rounded-full bg-green" aria-hidden="true" />
                {modelLabel}
              </button>
            )}

            {/* Dictation Voice Button */}
            <div
              className={cn(
                "flex size-7 shrink-0 items-center justify-center",
                wide ? "col-start-4 row-start-2" : "col-start-4 row-start-1",
              )}
            >
              <VoiceButton disabled={disabled} compact />
            </div>

            {/* Send or Stop button */}
            {busy ? (
              <button
                type="button"
                aria-label="Stop generating"
                onClick={onStop}
                className={cn(
                  "flex size-7 shrink-0 items-center justify-center rounded-[8px] bg-ink text-page transition-[background-color,color,transform] duration-150 active:scale-[0.94]",
                  wide ? "col-start-5 row-start-2" : "col-start-5 row-start-1",
                )}
              >
                <span className="size-2.5 rounded-[2px] bg-current" aria-hidden="true" />
              </button>
            ) : (
              <button
                type="button"
                aria-label="Send"
                disabled={!canSend}
                onClick={onSubmit}
                className={cn(
                  "flex size-7 shrink-0 items-center justify-center rounded-[8px] transition-[background-color,color,transform] duration-200 enabled:active:scale-[0.94]",
                  canSend ? "bg-ink text-surface shadow-btn" : "cursor-not-allowed bg-line-strong text-ink-2 opacity-60",
                  wide ? "col-start-5 row-start-2" : "col-start-5 row-start-1",
                )}
              >
                <Icon size={16} strokeWidth={2.4}>
                  <path d="M12 19V5M5 12l7-7 7 7" />
                </Icon>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
