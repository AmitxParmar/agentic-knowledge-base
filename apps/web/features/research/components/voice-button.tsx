/**
 * features/research/components/voice-button.tsx
 * ----------------------------------------------
 * Purpose:    Mic toggle for the voice research channel, styled as a compact
 *             icon button for the prompt bar (ADR-009). Live transcript,
 *             answer text, and per-stage latency render in a popover card
 *             anchored above the composer; the last exchange stays visible
 *             until the next toggle.
 * Dependencies: hooks/use-voice-chat.ts (ADR-009 styling)
 * Scope:      Voice channel UI surface.
 */

"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { useVoiceChat } from "../hooks/use-voice-chat";

export interface VoiceButtonProps {
  disabled?: boolean;
  /** Compact icon mode for the composer control row. */
  compact?: boolean;
  onTranscript?: (text: string) => void;
  onAnswer?: (text: string, citations: Array<{ chunk_id: string; source_ref?: string }>) => void;
}

export function VoiceButton({ disabled = false, compact = false, onTranscript, onAnswer }: VoiceButtonProps) {
  const { isListening, isSpeaking, error, latency, toggle } = useVoiceChat({
    disabled,
    onTranscript: (text) => {
      setLast({ ...lastAnswered(), transcript: text });
      onTranscript?.(text);
    },
    onAnswer: (text, citations) => {
      setLast({ transcript: text === "" ? "" : (lastAnswered().transcript ?? ""), answer: text, citations });
      onAnswer?.(text, citations);
    },
  });

  const [last, setLast] = useState<{
    transcript: string;
    answer: string;
    citations: Array<{ chunk_id: string; source_ref?: string }>;
  } | null>(null);

  const busy = isListening || isSpeaking;
  const showStats = latency && (latency.stt || latency.agent || latency.tts);
  const visible = Boolean(last || busy);

  const micButton = (
    <button
      type="button"
      onClick={() => {
        setLast(null);
        toggle();
      }}
      disabled={disabled && !isListening}
      aria-label={isListening ? "Stop voice question" : "Ask by voice"}
      aria-pressed={isListening}
      title={disabled ? "Ingest a document before using voice" : "Ask by voice"}
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-control",
        "transition-[background-color,color,transform] duration-150 enabled:active:scale-[0.94]",
        "disabled:cursor-not-allowed disabled:opacity-40",
        busy ? "bg-accent-tint text-accent-ink" : "text-ink-3 enabled:hover:bg-hover enabled:hover:text-ink",
      )}
    >
      {isListening ? (
        <span className="flex h-3.5 items-center gap-[2.5px]" aria-hidden="true">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="w-[2.5px] rounded-full bg-current"
              style={{ height: "100%", animation: `eq-bounce 900ms ease-in-out ${i * 150}ms infinite` }}
            />
          ))}
        </span>
      ) : (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
          <path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3" />
        </svg>
      )}
    </button>
  );

  if (!compact) {
    // Legacy inline layout retained for non-composer callers.
    return (
      <div>
        {visible && (
          <div className="rounded-card border border-line bg-surface-raised px-3 py-2 shadow-card">
            {last?.transcript && (
              <p className="text-[12.5px] text-ink-2">
                <span className="font-medium text-ink">You:</span> “{last.transcript}”
              </p>
            )}
            {last?.answer && (
              <p className="mt-1 text-[12.5px] text-ink-2">
                <span className="font-medium text-ink">Search:</span> {last.answer}
              </p>
            )}
            {showStats && (
              <p className="mt-1 font-mono text-[11px] text-ink-3 tabular-nums">
                STT {latency.stt ?? "—"}ms · AGENT {latency.agent ?? "—"}ms · TTS {latency.tts ?? "—"}ms
              </p>
            )}
            {isSpeaking && <p className="mt-1 text-[12px] text-accent-ink">speaking…</p>}
          </div>
        )}
        {error && (
          <p className="mt-1 text-[12px] text-red" role="alert">
            {error}
          </p>
        )}
        {micButton}
      </div>
    );
  }

  return (
    <div className="relative">
      {visible && (
        <div
          role="status"
          className="absolute bottom-full right-0 z-20 mb-2 w-72 rounded-card bg-surface-raised p-3 shadow-raised"
          style={{ animation: "pop-in 180ms var(--ease-out-expo) both", transformOrigin: "bottom right" }}
        >
          {isListening && !last?.transcript && (
            <p className="flex items-center gap-2 text-[12.5px] text-ink-2">
              <span className="size-1.5 animate-pulse rounded-full bg-red" aria-hidden="true" />
              Listening…
            </p>
          )}
          {isSpeaking && <p className="text-[12px] text-accent-ink">speaking…</p>}
          {last?.transcript && (
            <p className="text-[12.5px] leading-relaxed text-ink-2 [overflow-wrap:anywhere]">
              <span className="font-medium text-ink">You:</span> “{last.transcript}”
            </p>
          )}
          {last?.answer && (
            <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-2 [overflow-wrap:anywhere]">
              <span className="font-medium text-ink">Search:</span> {last.answer}
            </p>
          )}
          {showStats && (
            <p className="mt-2 border-t border-line pt-1.5 font-mono text-[11px] text-ink-3 tabular-nums">
              STT {latency.stt ?? "—"}ms · AGENT {latency.agent ?? "—"}ms · TTS {latency.tts ?? "—"}ms
            </p>
          )}
        </div>
      )}
      {error && (
        <p className="absolute bottom-full right-0 z-20 mb-2 w-56 rounded-chip bg-surface-raised px-2.5 py-1.5 text-[12px] text-red shadow-raised" role="alert">
          {error}
        </p>
      )}
      {micButton}
    </div>
  );

  function lastAnswered() {
    return last ?? { transcript: "", answer: "", citations: [] };
  }
}
