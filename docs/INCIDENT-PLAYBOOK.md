# Incident Playbook — Agentic Research Workspace

> Practical runbooks for the failures this stack actually has. Each entry:
> symptoms → diagnosis → mitigation → code touchpoints.
>
> Last updated: 2026-10-16

---

## 1. Embeddings provider down (Cohere)

**Symptoms**

- Ingestion jobs fail at the embedding stage (`stage=failed`, error mentions
  `EmbeddingError` or Cohere).
- Knowledge answers degrade or fail: retrieval cannot embed the query
  (HyDE / query embedding both go through the embedder).
- `/readyz` shows the embeddings probe failing or `embedding_versions`
  advisory flagging inconsistent `embedding_model` labels.

**Context**

- `ALLOW_EMBEDDING_FALLBACK=false` (default) — provider failure fails the job
  **loudly** instead of silently persisting hash vectors. This is intentional
  (ENGINEERING-IMPROVEMENTS P0 #1); do not flip it on to "fix" an outage.
- Embedding provenance: `chunks.embedding_model` records the model label per
  chunk (`embedder.embedding_model_label()`). Rows with `NULL` predate
  provenance tracking ("unversioned").

**Diagnosis**

```bash
curl -s http://<api>/readyz | jq           # embeddings probe + advisories
curl -s http://<api>/api/ingestion/jobs/failed | jq
# Cohere status: https://status.cohere.com
```

**Mitigation**

1. Wait for the provider to recover; confirm with `/readyz`.
2. Re-run affected jobs — stages are re-runnable:
   `POST /api/ingestion/jobs/{id}/retry` (deletes partial chunks via
   `reset_document_chunks` before re-embedding, so no duplicates).
3. If the model/version changed: re-embed documents and check
   `chunks.embedding_model` for mixed labels; unversioned (NULL) rows only
   need attention if the vector dim/space changed.

**Code touchpoints:** `src/retrieval/embedder.py`,
`src/ingestion/pipeline.py`, `app/main.py` (`_embedding_versions` advisory),
migration `d7e2f9a4b1c3`.

---

## 2. Redis down (Upstash rediss://)

**Symptoms**

- Ingestion uploads stay `queued` forever (arq cannot enqueue).
- `/readyz` Redis probe fails; chat endpoints that use the rate limiter or
  semantic/retrieval caches log connection errors.
- Voice/chat rate limiting starts failing open or closed depending on config.

**Diagnosis**

```bash
redis-cli -u "$REDIS_URL" ping        # or check Upstash console
curl -s http://<api>/readyz | jq
```

**Mitigation**

1. Upstash: check the database status + monthly command budget (free tier
   can hard-stop mid-month).
2. After recovery: re-upload or re-run stuck jobs
   (`GET /api/ingestion/jobs/failed` → `POST /jobs/{id}/retry`).
3. Caches (semantic, retrieval) rebuild themselves on miss — no action
   needed. Rate-limit windows reset naturally.

**Code touchpoints:** `app/workers.py` (arq), `src/shared/rate_limit.py`,
`src/shared/retrieval_cache.py`, `app/main.py` readyz probe.

---

## 3. Neon cold start / Postgres slow first connection

**Symptoms**

- First request after idle takes 5–30 s; `alembic upgrade head` or app boot
  times out on the first attempt.
- `/readyz` DB probe slow or timing out on first boot.

**Diagnosis**

- Neon free tier suspends idle computes; the first connection resumes it.
  A timeout on the **first** attempt followed by success on retry is the
  signature. Check Neon console for "compute suspending/suspended".

**Mitigation**

1. Retry once — the compute wakes and subsequent queries are fast.
2. Long migrations: run `alembic upgrade head` again if it timed out
   (migrations are idempotent at head; verify with `alembic current`).
3. If it recurs in production traffic, keep the compute warm (Neon setting)
   or accept cold-start latency on the first request after idle.

**Code touchpoints:** `app/settings.py` (pool tuning), `alembic/env.py`.

---

## 4. TTS / voice channel failures (Groq Orpheus)

**Symptoms**

- Voice answers arrive as text but no audio plays; server log:
  `voice_router: TTS failed, sending text-only`.
- `model_gateway.speech` errors: `ProviderError` (TTS provider is
  unavailable) or `RateLimitError` (TTS provider is rate limited).

**Diagnosis**

| Error from Groq | Meaning | Fix |
|---|---|---|
| `model_terms_required` (400) | Org admin has not accepted Orpheus terms | Accept once: https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english |
| 429 | Free-tier cap (10 RPM / 100 req/day on the model) | Wait; a typical answer is ~5 requests. Developer tier removes the cap |
| 5xx / network | Provider incident | Text-only fallback already covers it; retry later |

- Live probe: `LIVE_TTS_TESTS=1 uv run pytest tests/research/test_voice.py -q`
  (from `apps/api/`).

**Mitigation**: voice always degrades to a text answer — no user-facing
failure. The `tts_chunks()` seam means a provider swap is one module + an
ADR-006 amendment.

**Code touchpoints:** `src/shared/model_gateway.py` (`speech`),
`src/research/voice_tts.py`, `src/research/voice_router.py`,
ADR-006 (amended 2026-10-16).

---

## 5. Model providers down (Groq → OpenRouter exhausted)

**Symptoms**

- Answers fail with "Model providers are unavailable…" or "rate limited…".
- `/readyz` `model_providers` advisory shows the circuit breaker open
  (`src/shared/circuit_breaker.py` snapshot: 5 fails/30 s → skip + 60 s
  cooldown + half-open probe).

**Diagnosis**

```bash
curl -s http://<api>/readyz | jq '.advisories.model_providers'
curl -s -X POST http://<api>/test-llm     # only when APP_DEBUG=true
```

**Mitigation**: wait out the cooldown (breaker closes on the next successful
half-open probe); check Groq/OpenRouter status pages; verify keys in
`apps/api/.env` if both providers fail simultaneously.

**Code touchpoints:** `src/shared/model_gateway.py`,
`src/shared/circuit_breaker.py`, `app/main.py` readyz advisory.
