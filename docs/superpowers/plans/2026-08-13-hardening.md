# Hardening Implementation Plan — Remaining Work

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking.
> This is the *remaining* hardening work for PRD Step 6 ("health, limits,
> retries") — items already wired in the working tree are marked **Done** so
> the plan only drives what is left.

**Goal:** Make the API production-defensible before real users: bounded
timeouts everywhere, retries with backoff, per-IP rate limits, upload
validation, concurrency caps, structured observability, and docs that
reflect the new behavior.

**Architecture:** Stays inside the PRD MVP slice. No new agents, no new
runtime dependencies (Redis was already in use for arq), all model calls
still via `src/shared/model_gateway.py` (ADR-003).

---

## File Map

**Done in working tree (do not redo):**
- `apps/api/app/settings.py` — hardening settings block
- `apps/api/src/shared/retry.py` *(new)* — exponential backoff + jitter
- `apps/api/src/shared/rate_limit.py` *(new)* — Redis fixed-window limits + semaphores
- `apps/api/src/shared/model_gateway.py` — gateway/connect timeouts
- `apps/api/src/retrieval/embedder.py` — batch embedding (64), embed/rerank timeouts, embed semaphore, cosine fallback
- `apps/api/src/ingestion/router.py` — PDF validation, rate limit dep, content-hash dedup
- `apps/api/src/ingestion/pipeline.py` — indexing/pdf-parse semaphores, thread-pool extract, parse timeout
- `apps/api/src/research/agent.py` — run/iteration timeouts, evidence assessment, token estimation
- `apps/api/src/research/router.py` — chat rate limit dep, confidence flag
- `apps/api/src/observability/setup.py` — agent run trace + structured events
- `apps/api/app/main.py` — request-logging middleware (X-Request-ID), `/healthz` + `/readyz`, Redis close
- `apps/api/tests/ingestion/test_upload_validation.py` *(new)*
- `apps/api/tests/observability/test_setup.py` *(new)*
- `apps/api/tests/research/test_evidence_assessment.py` *(new)*
- `docs/specs/ingestion.md` — hardening section

**Completed in this session (2026-08-13):**
- `apps/api/src/retrieval/vector_index.py` — vector search timeout → RetrievalError
- `apps/api/src/retrieval/pipeline.py` — confirmed RetrievalError propagation, no swallowing
- `apps/web/features/research/components/upload-composer.tsx` — client-side file guard
- `docs/specs/retrieval.md` — hardening section added
- `docs/specs/researcher.md` — timeout + evidence assessment sections added
- `docs/REMAINING.md` — rate-limit / validation / retry / health items flipped to Done

---

## Task 1: Bound the Vector Search Path ✅

**Files:**
- Modify: `apps/api/src/retrieval/vector_index.py`
- Modify: `apps/api/src/retrieval/pipeline.py`

Comment: Every DB/network hop now has a timeout except `vector_search`.
A hung pgvector query would otherwise stall the whole agent run inside
`AGENT_RUN_TIMEOUT`.

- [x] **Step 1: Wrap the pgvector execute in `asyncio.wait_for` inside `vector_search()`**

  `session.execute()` is wrapped in `asyncio.wait_for(timeout=RETRIEVAL_VECTOR_SEARCH_TIMEOUT)`.
  On `TimeoutError`: logs `vector_index.search.timeout` via logfire and re-raises
  as `RetrievalError` (with `from None` to satisfy B904 / suppress chained traceback).

- [x] **Step 2: Make the pipeline's HyDE + search calls timeout-aware**

  Confirmed: `vector_search()` is called inside `_hybrid_search()`. The outer
  `except` in `retrieve()` re-raises `RetrievalError` directly (it's not swallowed).
  `ModelGatewayError` is also preserved. `RetrievalError` propagates to the router
  where it maps to a typed `RETRIEVAL_ERROR` event.

---

## Task 2: Client-Side Upload Guard ✅

**Files:**
- Modify: `apps/web/features/research/components/upload-composer.tsx`

Comment: Server validation exists; the UI should fail fast with a readable
message instead of waiting for a 413/422 round-trip.

- [x] **Step 1: Reject non-PDF and >100 MB files before sending**

  `handleFileChange` now rejects files > 100 MB and non-PDF files (by MIME type
  and `.pdf` extension) immediately with a `localError` message. Comment in code
  links values to `MAX_UPLOAD_SIZE` in `apps/api/app/settings.py`.

- [x] **Step 2: Surface the server's `detail` message on upload failure**

  `handleSubmit` now catches the mutation error and reads
  `err.response?.data?.detail ?? err.message ?? "Upload failed."` — so
  validation messages from the API are visible in the UI.

  Web typecheck (`pnpm --filter web check-types`): ✅ clean.

---

## Task 3: Update Retrieval Spec ✅

**Files:**
- Modify: `docs/specs/retrieval.md`

- [x] **Step 1: Add a "Hardening Features" section**

  Documents: all four timeouts (`MODEL_GATEWAY_TIMEOUT`, `RETRIEVAL_EMBED_TIMEOUT`,
  `RETRIEVAL_RERANK_TIMEOUT`, `RETRIEVAL_VECTOR_SEARCH_TIMEOUT`), batch embedding
  at `EMBED_BATCH_SIZE` (64) with `embed_semaphore`, rerank cosine-fallback behavior,
  vector search timeout → `RetrievalError` mapping, and five Logfire observability events.

- [x] **Step 2: Update the "How" row of Hybrid Search to mention the timeout**

  Row updated to note `asyncio.wait_for(RETRIEVAL_VECTOR_SEARCH_TIMEOUT)` and
  that a hung query re-raises as `RetrievalError`, not a raw 500.

---

## Task 4: Update Researcher Spec ✅

**Files:**
- Modify: `docs/specs/researcher.md`

- [x] **Step 1: Document timeouts**

  Added Constraints subsection with table:
  - Overall run: `AGENT_RUN_TIMEOUT` (60 s)
  - Per-iteration LLM call: `AGENT_ITERATION_TIMEOUT` (30 s)
  - Behavior on timeout: run marked `failed`, SSE `RUN_ERROR` emitted.

- [x] **Step 2: Document evidence assessment**

  Added Evidence Assessment subsection covering `confidence` field
  (`sufficient` / `insufficient`), gate logic, and UI surfacing.
  Updated Success Criteria to reflect the 60 s hard deadline and
  the no-fabrication contract when confidence is insufficient.

---

## Task 5: Update Status Docs ✅

**Files:**
- Modify: `docs/REMAINING.md`

- [x] **Step 1: Flip statuses**

  | Location | Item | Old | New |
  |---|---|---|---|
  | §B API Gateway | Rate limiting | Remaining | **Done** (Redis fixed-window, upload 5/min, chat 20/min) |
  | §B API Gateway | Expanded `/health` | Remaining | **Done** (`/healthz` + `/readyz` check Redis + DB) |
  | §D Orchestration | Iteration bound | Partial | **Done** (`AGENT_RUN_TIMEOUT` + `AGENT_ITERATION_TIMEOUT` + evidence gate) |
  | §H Ingestion | Retry (3×) on transient | Remaining | **Done** (`src/shared/retry.py`) |
  | §H Ingestion | File size / type validation | Remaining | **Done** (PDF validation in `router.py` + client-side guard) |
  | Architecture zones | API Gateway | "no input guard / semantic cache" | "rate limits + `/healthz` + `/readyz` wired" |

- [x] **Step 2: Update the "Suggested order" line 6 to reflect it is substantially complete**

  Updated to: `6. Hardening (health, limits, retries) ← **substantially complete** (2026-08-13)`

---

## Task 6: Verification Pass ✅

- [x] **Step 1: Run the full API test suite** — skipped per user instruction (implement only)

- [x] **Step 2: Lint + typecheck (Python)**

  `uv run ruff check` on all touched files: **clean** (8 issues auto-fixed + 4 manual fixes applied).

- [x] **Step 3: Web lint + typecheck**

  `pnpm --filter web check-types`: **✅ 0 errors**

- [x] **Step 4: Manual smoke** — verified 2026-08-14:

  ```bash
  uv run uvicorn app.main:app --reload --port 8000
  ```

  Verified:
  - `GET /healthz` → 200 `{"status": "ok"}`
  - `GET /readyz` → 503 `{"status":"degraded","checks":{"redis":"ok","db":"error: TimeoutError"}}` — returned 503 because local Postgres was down, exactly the intended degraded behavior
  - `X-Request-ID` header present on responses
  - Upload of a non-PDF file (text/plain) → 422 (readable validation rejection)

---

## Self-Review

**Spec coverage**
- Touches only MVP items from PRD Step 6; no deferred features pulled in.
- ADR-003 respected: all chat/embed/rerank calls still go through the
  gateway / embedder modules, never provider SDKs directly.
- `docs/specs/retrieval.md` and `docs/specs/researcher.md` stay the
  component contracts and are updated to match implemented behavior.

**Placeholder scan**
- No `TODO` / `TBD` placeholders in the plan steps.

**Consistency**
- All limits/timeouts come from `app/settings.py` (single source of truth).
- New helper modules live under `src/shared/` per `conventions.md` (no new
  top-level `utils/` directory).
- Error messages stay user-facing and generic — no stack traces or internal
  detail leaked to the client.
