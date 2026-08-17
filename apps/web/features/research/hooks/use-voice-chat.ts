/**
 * features/research/hooks/use-voice-chat.ts
 * -------------------------------------------
 * Purpose:    Browser voice channel for the research agent. Captures the mic
 *             as 16 kHz mono float32 PCM, streams it as binary WebSocket
 *             frames to /api/research/ws/voice, and plays back the streamed
 *             MP3 TTS chunks. Mirrors the text chat flow: transcript →
 *             research run → answer + citations, with a latency breakdown.
 *
 * Transport protocol (ADR-006):
 *     client → server  binary: raw f32 PCM frames
 *     client → server  text:   {"action":"start"} | {"action":"stop"}
 *     server → client  binary: MP3 audio chunks (TTS)
 *     server → client  text:   {"type":"ready","transcript","answer","done",
 *                               "latency","error"}
 *
 * We use an AudioWorklet (inlined via Blob, no bundle step) whose processor
 * coalesces 512-sample frames; the AudioContext is constructed at 16 kHz so
 * the browser resamples the mic to the rate the server expects.
 * Dependencies: lib/env.ts, research-service.ts (headers/auth)
 * Scope:        Voice capture + playback for the research feature.
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "@/lib/env";

const SAMPLE_RATE = 16000;
const FRAME = 512; // ~32 ms @ 16 kHz — matches the server VAD window

/** The inline AudioWorklet processor code (string → Blob → addModule). */
const PROCESSOR_SOURCE = `
class VoicePcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(0);
  }
  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const channel = input[0];
    // Append to the pending buffer, then emit complete 512-sample frames.
    const joined = new Float32Array(this.buffer.length + channel.length);
    joined.set(this.buffer, 0);
    joined.set(channel, this.buffer.length);
    let offset = 0;
    while (joined.length - offset >= ${FRAME}) {
      this.port.postMessage(joined.slice(offset, offset + ${FRAME}));
      offset += ${FRAME};
    }
    this.buffer = offset < joined.length ? joined.slice(offset) : new Float32Array(0);
    return true;
  }
}
registerProcessor("voice-pcm-processor", VoicePcmProcessor);
`;

export interface VoiceStageLatency {
  stt?: number;
  agent?: number;
  tts?: number;
}

export interface UseVoiceChatOptions {
  /** Disable mic/WS when the workspace isn't ready (no ingested documents). */
  disabled?: boolean;
  onTranscript?: (text: string) => void;
  onAnswer?: (text: string, citations: Array<{ chunk_id: string; source_ref?: string }>) => void;
  onStage?: (stage: string) => void;
}

export function useVoiceChat({
  disabled = false,
  onTranscript,
  onAnswer,
  onStage,
}: UseVoiceChatOptions = {}) {
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [latency, setLatency] = useState<VoiceStageLatency | null>(null);

  // Refs so the WebSocket handlers don't go stale between renders.
  const wsRef = useRef<WebSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const playbackQueuesRef = useRef<AudioBufferSourceNode[]>([]);
  const disabledRef = useRef(disabled);
  disabledRef.current = disabled;

  const callbacksRef = useRef({ onTranscript, onAnswer, onStage });
  callbacksRef.current = { onTranscript, onAnswer, onStage };

  const stopPlayback = useCallback(() => {
    for (const src of playbackQueuesRef.current) {
      try {
        src.stop();
      } catch {
        /* already stopped */
      }
    }
    playbackQueuesRef.current = [];
    setIsSpeaking(false);
  }, []);

  const playMp3Chunk = useCallback(async (arrayBuffer: ArrayBuffer) => {
    const ctx = audioCtxRef.current;
    if (!ctx) return;
    try {
      const audioBuffer = await ctx.decodeAudioData(arrayBuffer);
      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(ctx.destination);
      playbackQueuesRef.current.push(source);
      source.onended = () => {
        playbackQueuesRef.current = playbackQueuesRef.current.filter((s) => s !== source);
        if (playbackQueuesRef.current.length === 0) setIsSpeaking(false);
      };
      source.start();
    } catch {
      // Undecodable chunk (e.g. the client closed mid-stream) — ignore.
    }
  }, []);

  const handleServerText = useCallback(
    (event: MessageEvent) => {
      let payload: { type: string; [k: string]: unknown };
      try {
        payload = JSON.parse(event.data as string);
      } catch {
        return;
      }
      switch (payload.type) {
        case "transcript":
          callbacksRef.current.onTranscript?.(String(payload.text ?? ""));
          break;
        case "stage":
          callbacksRef.current.onStage?.(String(payload.stage ?? ""));
          break;
        case "answer": {
          const text = String(payload.text ?? "");
          const citations = Array.isArray(payload.citations) ? payload.citations : [];
          callbacksRef.current.onAnswer?.(text, citations);
          setIsSpeaking(true);
          break;
        }
        case "latency":
          setLatency((payload.stages as VoiceStageLatency) ?? null);
          break;
        case "error":
          setError(String(payload.message ?? "Voice error"));
          break;
        case "done":
          break;
        default:
          break;
      }
    },
    [],
  );

  const handleServerBinary = useCallback(
    (event: MessageEvent) => {
      if (!(event.data instanceof Blob) && !(event.data instanceof ArrayBuffer)) return;
      if (event.data instanceof Blob) {
        // Binary frames over WebSocket arrive as Blob by default.
        void event.data.arrayBuffer().then(playMp3Chunk);
      } else {
        void playMp3Chunk(event.data);
      }
    },
    [playMp3Chunk],
  );

  const close = useCallback(() => {
    stopPlayback();
    workletNodeRef.current?.port.close();
    sourceNodeRef.current?.disconnect();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    wsRef.current?.close();
    wsRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    workletNodeRef.current = null;
    sourceNodeRef.current = null;
    streamRef.current = null;
    setIsListening(false);
  }, [stopPlayback]);

  const start = useCallback(async () => {
    if (disabledRef.current) {
      setError("Ingest a document before using voice.");
      return;
    }
    setError(null);
    setLatency(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
      audioCtxRef.current = ctx;
      await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([PROCESSOR_SOURCE], { type: "application/javascript" })));

      const source = ctx.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(ctx, "voice-pcm-processor");
      worklet.port.onmessage = (event) => {
        const samples = event.data as Float32Array;
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(samples.buffer as ArrayBuffer);
        }
      };
      source.connect(worklet);
      worklet.connect(ctx.destination); // keep the graph alive (silent)

      sourceNodeRef.current = source;
      workletNodeRef.current = worklet;

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${protocol}//${API_BASE_URL.replace(/^https?:\/\//, "")}/api/research/ws/voice`);
      wsRef.current = ws;
      ws.binaryType = "arraybuffer";

      ws.onmessage = (event) => {
        if (typeof event.data === "string") handleServerText(event);
        else handleServerBinary(event);
      };
      ws.onerror = () => setError("Voice connection failed.");
      ws.onclose = () => {
        if (wsRef.current === ws) {
          stopPlayback();
          setIsListening(false);
        }
      };
      ws.onopen = () => {
        setIsListening(true);
        ws.send(JSON.stringify({ action: "start" }));
      };
    } catch {
      // getUserMedia denied or AudioWorklet unsupported.
      setError("Mic unavailable or permission denied.");
      close();
    }
  }, [close, handleServerBinary, handleServerText, stopPlayback]);

  const stop = useCallback(() => {
    // Ask the server to flush any in-flight utterance, then tear down.
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "stop" }));
    }
    close();
  }, [close]);

  const toggle = useCallback(() => {
    if (isListening) void stop();
    else void start();
  }, [isListening, start, stop]);

  // Teardown on unmount.
  useEffect(() => () => close(), [close]);

  return {
    isListening,
    isSpeaking,
    error,
    latency,
    start,
    stop,
    toggle,
  };
}