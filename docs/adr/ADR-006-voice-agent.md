# ADR-006: Voice Agent (Real-time STT + Streaming TTS)

## Status

Accepted. Adds a bidirectional real-time voice channel to the research
workspace, layered on the existing WebSocket transport.

**Amended 2026-10-16 — TTS provider swap:** edge-tts (Microsoft Edge's
unofficial neural-TTS service) started failing with `403 WSServerHandshakeError`
during handshake; the dependency is being replaced by **Groq Orpheus**
(`canopylabs/orpheus-v1-english`) — a hosted API riding the model gateway's
existing Groq credential. Local TTS engines (Piper, Kokoro) are additionally
ruled out by the deployment target: Render free tier (512 MB RAM, shared CPU)
cannot host model inference. `tts_chunks()` remains the single swap seam.

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
3. No new API keys. TTS and STT must be self-hosted already-installed, free
   and keyless, or ride an **existing** gateway credential (no new signup,
   no new secret).
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

### TTS: Groq Orpheus (hosted, via the Model Gateway) — supersedes edge-tts

- `canopylabs/orpheus-v1-english` on Groq's OpenAI-compatible speech endpoint
  (`https://api.groq.com/openai/v1/audio/speech`) — **hosted** (zero CPU/RAM
  on Render free tier), **no new API key** (reuses `GROQ_API_KEY` through the
  gateway), free tier without a credit card.
- Called through `model_gateway.speech()` — same rule as chat: no provider
  SDK in feature code; httpx (already a dependency) is the transport.
- One request is capped at **200 characters** and returns a complete **WAV**
  (no server-side streaming), so `voice_tts.split_for_tts()` sentence-chunks
  the answer; each WAV chunk is independently decodable by the browser's
  `AudioContext.decodeAudioData()`. Chunk N plays while chunk N+1 synthesizes
  — synthesis pipelines with playback, preserving the perceived-latency win.
- Free-tier rate limits are per-model (10 RPM / 100 requests/day on Orpheus)
  and do not consume the chat models' quota; a typical answer is ~5 requests.
- Voice `hannah` default, configurable via `VOICE_TTS_VOICE`.

### Transport: one binary WebSocket `/api/research/ws/voice`

Binary frames carry PCM (client→server) and WAV (server→client); JSON text
frames carry control + metadata. Mirrors the existing `/ws` research
endpoint's shape (Depends auth, session, progress vocabulary, error codes).

## Consequences

### Positive

- Full bidirectional real-time voice reusing the agent, gateway, and WS
  layer — the phrase voice-agent JDs actually use.
- Sub-second STT baseline (small + int8) with a tunable knob.
- Chunked TTS pipelines synthesis with playback, cutting perceived latency.
- Zero new API keys (existing Groq credential) and the swap **retires** the
  `edge-tts` dependency — net one Python dep removed.

### Negative / mitigations

| Risk | Mitigation |
|---|---|
| faster-whisper large on CPU too slow | Default `small`; configurable model; int8 quantization |
| Orpheus free tier: 10 RPM / 100 requests/day | Sentence-chunking keeps a typical answer ≤ 6 requests; text-only fallback on TTS failure; Developer tier removes the cap if needed |
| Orpheus 200-char input cap | `split_for_tts()` splits on sentence → clause → word boundaries; pieces never exceed the cap |
| Non-streaming WAV responses | Chunked pipelining + buffered playback of each chunk (`decodeAudioData`) |
| Groq model terms must be accepted once by the org admin | One-time accept in the Groq console playground; `test_voice.py` carries a live-gated probe |
| Hosted-provider churn (Groq already replaced PlayAI with Orpheus) | `tts_chunks()` seam: a swap is one module + an ADR amendment |
| VAD misjudges utterance end | Silero is state-of-the-art for this; `VOICE_VAD_SILENCE_MS`, threshold, min-speech keys are tunable |

### Alternatives considered

| Alternative | Why rejected |
|---|---|
| Deepgram / AssemblyAI realtime STT | New API key + cost; defeats "self-hosted" constraint |
| ElevenLabs / Azure / Google Cloud TTS | Official hosted APIs, but ElevenLabs free = 10k chars/mo (~10 answers); Azure/Google free tiers need a new account + billing setup — rejected against zero-new-setup Orpheus |
| Local engines (Piper, Kokoro-ONNX) | Free and offline, but Render free tier (512 MB, shared CPU) cannot reliably host inference — rejected by the deployment constraint |
| Bump edge-tts 7.2.8 → 7.3.1 | Same unofficial Microsoft endpoint already returning 403 — stopgap only |
| Whisper streaming (`whisper_streaming` wrapper) | Extra dep to simulate streaming; Silero endpointing + batched buﬀer is simpler and genuinely correct |
| WebRTC transport | Browser + server WebSocket covers it; no reason to add a new transport |
| pyannote / diarization | Single-user channel; YAGNI |

## Approved Libraries update

Add to `docs/conventions.md` → Approved Libraries table:

| Concern | Library |
|---|---|
| TTS (hosted) | Groq Orpheus via Model Gateway (`model_gateway.speech`) |
| STT + VAD endpointing | faster-whisper (extend existing row) |

## Packages

```bash
# from apps/api/ — the swap removes a package; nothing new is added:
uv remove edge-tts
```
