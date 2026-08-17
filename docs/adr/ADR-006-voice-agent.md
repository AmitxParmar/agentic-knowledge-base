# ADR-006: Voice Agent (Real-time STT + Streaming TTS)

## Status

Accepted. Adds a bidirectional real-time voice channel to the research
workspace, layered on the existing WebSocket transport.

## Context

The research workspace accepts text questions and streams citation-backed
answers via AG-UI SSE and a legacy `/ws` WebSocket. Voice-agent job
descriptions emphasize bidirectional real-time speech: streaming speech-totext (STT) on input, streamed text-to-speech (TTS) on output. Today the repo
has only batch STT (`faster-whisper` inside the ingestion pipeline) and no
TTS at all.

Voice differs from batch transcription in one critical way: the server does
not receive a complete file. PCM audio frames arrive continuously over a
socket, and the server must decide **when the user stopped speaking**
(endpointing), transcribe only the buffered utterance, run the existing
Research Agent, and stream synthesized speech back before the user gets
impatient.

## Constraints

1. Reuse the existing stack: LangGraph agent (`src/research/agent.py`),
   Model Gateway (`src/shared/model_gateway.py`), WebSocket infra
   (`src/shared/progress.py`, `websockets>=15`).
2. No new frontend audio dependency — the browser Web Audio API covers mic
   capture and playback.
3. No new API keys. The model gateway requires credentials; TTS and STT must
   either be self-hosted already-installed, or free and keyless.
4. Citations must survive the voice pipeline exactly as they do for text.

## Decision

### STT: faster-whisper (already installed) + Silero VAD for endpointing

- faster-whisper 1.x includes a bundled **Silero VAD ONNX model
  (`silero_vad_v6.onnx`)** run through onnxruntime (already a transitive
  dependency of faster-whisper).
- We do **not** transcribe frame-by-frame (faster-whisper's `transcribe()`
  needs the full utterance as a `np.ndarray`). Instead:
  1. Buffer incoming PCM frames (16 kHz mono float32).
  2. Run Silero VAD per 512-sample window to detect speech on/off.
  3. When trailing silence exceeds a threshold (`VOICE_VAD_SILENCE_MS`),
     end the utterance and hand the buffered array to faster-whisper.
- Model: `large-v3` is accurate but ~5.4x realtime on CPU — too slow for an
  interactive loop. Default to `small` (int8, beam_size=1) for sub-second
  latency on short utterances; `VOICE_STT_MODEL` lets an operator trade
  accuracy for latency (`distil-small.en`, `large-v3-turbo`).

### TTS: edge-tts (new dependency, ADR approval)

- &#91;`edge-tts`&#93;(https://github.com/rany2/edge-tts) calls Microsoft Edge's
  neural TTS service over HTTPS — **free, no API key**, streams MP3 chunks
  as an async generator (`Communicate.stream()`).
- Yields `audio-24khz-48kbitrate-mono-mp3` chunks as they are synthesized,
  so the first audio byte reaches the browser before the agent's final token
  is complete when the answer is long.
- Browser `AudioContext.decodeAudioData()` decodes MP3 natively — no
  frontend audio dependency.
- Voice `en-US-AriaNeural` default, configurable via `VOICE_TTS_VOICE`.

### Transport: one binary WebSocket `/api/research/ws/voice`

Binary frames carry PCM (client→server) and MP3 (server→client); JSON text
frames carry control + metadata. Mirrors the existing `/ws` research
endpoint's shape (Depends auth, session, progress vocabulary, error codes).

## Consequences

### Positive

- Full bidirectional real-time voice reusing the agent, gateway, and WS
  layer — the phrase voice-agent JDs actually use.
- Sub-second STT baseline (small + int8) with a tunable knob.
- Streaming TTS overlaps the agent's generation tail, cutting perceived
  latency.
- Zero new API keys; one new Python dep.

### Negative / mitigations

| Risk | Mitigation |
|---|---|
| faster-whisper large on CPU too slow | Default `small`; configurable model; int8 quantization |
| edge-tts depends on Microsoft service availability | Unfurl-able; falls back to text-only answer on failure |
| VAD misjudges utterance end | Silero is state-of-the-art for this; `VOICE_VAD_SILENCE_MS`, threshold, min-speech keys are tunable |
| MP3 decode in browser | `AudioContext.decodeAudioData` is native |

### Alternatives considered

| Alternative | Why rejected |
|---|---|
| Deepgram / AssemblyAI realtime STT | New API key + cost; defeats "self-hosted" constraint |
| ElevenLabs / Azure TTS | New API key + cost; ADR closes the gap with edge-tts for free |
| Whisper streaming (`whisper_streaming` wrapper) | Extra dep to simulate streaming; Silero endpointing + batched buﬀer is simpler and genuinely correct |
| WebRTC transport | Browser + server WebSocket covers it; no reason to add a new transport |
| pyannote / diarization | Single-user channel; YAGNI |

## Approved Libraries update

Add to `docs/conventions.md` → Approved Libraries table:

| Concern | Library |
|---|---|
| TTS (streaming, keyless) | edge-tts |
| STT + VAD endpointing | faster-whisper (extend existing row) |

## Packages

```bash
uv add "edge-tts>=7.0"   # from apps/api/
```