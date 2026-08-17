/**
 * features/research/components/voice-button.tsx
 * ----------------------------------------------
 * Purpose:    Mic toggle for the voice research channel. Compact in the
 *             composer; expands to show live transcript, answer text, and the
 *             per-stage latency breakdown after a turn. The last exchange
 *             stays rendered until the next toggle so answers are readable.
 * Dependencies: hooks/use-voice-chat.ts, voice-button.module.css
 * Scope:      Voice channel UI surface.
 */

"use client";

import { useState } from "react";
import { useVoiceChat } from "../hooks/use-voice-chat";
import styles from "./voice-button.module.css";

export interface VoiceButtonProps {
  disabled?: boolean;
  onTranscript?: (text: string) => void;
  onAnswer?: (text: string, citations: Array<{ chunk_id: string; source_ref?: string }>) => void;
}

export function VoiceButton({ disabled = false, onTranscript, onAnswer }: VoiceButtonProps) {
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
  const visible = last || busy;

  return (
    <div className={styles.wrap}>
      {visible && (
        <div className={styles.status}>
          {last?.transcript && (
            <span className={styles.transcript}>
              <span className={styles.kind}>YOU:</span> “{last.transcript}”
            </span>
          )}
          {busy && isListening && !last?.transcript && <span className={styles.hint}>listening…</span>}
          {last?.answer && (
            <span className={styles.answer}>
              <span className={styles.kind}>SEARCH:</span> {last.answer}
            </span>
          )}
          {showStats && (
            <span className={styles.latency}>
              STT {latency.stt ?? "—"}ms · AGENT {latency.agent ?? "—"}ms · TTS {latency.tts ?? "—"}ms
            </span>
          )}
          {isSpeaking && <span className={styles.speaking}>speaking…</span>}
        </div>
      )}
      {error && <span className={styles.error}>{error}</span>}
      <button
        type="button"
        className={`${styles.mic} ${isListening ? styles.listening : ""} ${isSpeaking ? styles.speaking : ""}`}
        onClick={() => {
          setLast(null);
          toggle();
        }}
        disabled={disabled && !isListening}
        aria-label={isListening ? "Stop voice" : "Start voice"}
        title={disabled ? "Ingest a document before using voice" : "Voice question"}
      >
        {isListening ? "■ STOP" : "MIC"}
      </button>
    </div>
  );

  function lastAnswered() {
    return last ?? { transcript: "", answer: "", citations: [] };
  }
}