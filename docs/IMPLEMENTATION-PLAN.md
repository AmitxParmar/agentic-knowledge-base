# Implementation Plan — Reliability, Retrieval, and Agent Runtime Hardening

> Execution plan derived from the architecture review of the Agentic Research
> Workspace. Every item is checked against the live code in `apps/api/`, not
> just the architecture diagram.
>
> **Status legend**

| Mark | Meaning |
|---|---|
| `[x]` | Verified done in the current codebase — keep it green |
| `[ ]` | Not done, or only partially done — this plan's work |
| `[~]` | Exists but needs verification, tuning, or hardening |

> **Priority legend**

| Priority | Meaning |
|---|---|
| **P0** | Production failure mode (OOM, auth bypass, data leak, silent data loss) |
| **P1** | Correctness / cost / quality multiplier |
| **P2** | Architecture leverage once the loop is measured |
| **P3** | Nice-to-have, wait for usage signal |

**Last updated:** 2026-10-30

---

## 1. Executive Assessment

The system is architecturally disciplined for a 512 MB, single-container
deployment. The important decisions are already recorded and implemented:

- **Unified data plane** — pgvector + `tsvector` in Neon Postgres replaced the
  in-process Turbovec index, removing cold-start rebuilds and cross-store
  drift.
- **Clean provider seams** — all completions go through
  `src/shared/model_gateway.py` (Groq → OpenRouter); TTS goes through
  `model_gateway.speech()`.
- **Zero-dependency hardening** — deterministic secret redaction (ADR-010),
  HS256 workspace-scoped JWT (ADR-008), and a Redis semantic answer cache
  (ADR-007) without new containers.

The review's core conclusion still holds: **the next gains are not new agent
nodes.** They are durability, memory isolation, retrieval quality, and
measurement. Adding Planner/Critic/Confidence-Scorer nodes before those are
done would multiply latency and Groq rate-limit pressure without improving
groundedness.

### 1.1 Review claims vs. actual code (reconciled)

Several review findings are already stale. Do not rebuild what exists.

| Review claim | Actual state | Evidence |
|---|---|---|
| Ingestion has no content hash / idempotency | **Done** — SHA-256 `content_hash`, `(workspace_id, content_hash)` dedup, arq `_job_id` | `src/ingestion/router.py:77-99,175-227` |
| Ingestion has no retries | **Partial** — `max_tries=3`, retry endpoint exists; no exponential backoff, no explicit DLQ stage, no delta chunk reuse | `app/workers.py:70-77`, `src/ingestion/router.py:280-314` |
| No LangGraph checkpointer | **Done** — custom asyncpg-backed `AsyncPostgresSaver` in `langgraph_checkpoints` | `src/research/checkpoint.py` |
| Checkpoint table bloat unmanaged | **Open** — no TTL cleanup job | `src/research/checkpoint.py` |
| Semantic cache uses latin-1 strings / full hash fetch | **Done** — packed `float32` bytes and packed index | `src/shared/semantic_cache.py:97-120` |
| Semantic cache ignores conversation history | **Open** — exact key is `(workspace, query_hash)` only | `src/shared/semantic_cache.py:108` |
| Cache delete flushes whole workspace | **Open** — only `invalidate_workspace()` exists | `src/shared/semantic_cache.py:328` |
| Hybrid retrieval is a single CTE | **Open** — allowlist query + dense query + FTS query, RRF in Python | `src/retrieval/pipeline.py:185-258` |
| Chunks lack document/section context | **Open** — no contextual header at ingest | `src/ingestion/chunker.py` |
| Reranker present | **Done** — Cohere rerank applied to candidates | `src/retrieval/pipeline.py:392-398` |
| Reranker score gate / abstention | **Open** — no `τ_keep` / `τ_abstain` | `src/retrieval/pipeline.py:53-150` |
| Claim verifier exists | **Open** — no `src/research/verifier.py` | — |
| Tiered model routing | **Open** — single model path, no `role=` parameter | `src/shared/model_gateway.py:469-520` |
| Cost ledger | **Partial** — `research_runs.token_count` only; no USD/latency/cached tokens | `src/research/models.py:55-57` |
| Prompt-injection spotlighting | **Partial** — `wrap_document()` + scanners exist; no per-run nonce, no chunk-level tagging, no startup guard | `src/shared/prompt_safety.py:85`, `app/settings.py:227` |
| Auth defaults | **Partial** — JWT implemented, `AUTH_MODE=stub` remains default, no production startup guard | `app/settings.py:224-228` |
| Eval harness | **Partial** — retrieval + answer eval scripts exist, CI gate is non-blocking | `.github/workflows/ci.yml:76-104` |
| Single-container memory risk | **Open** — `max_jobs=4` + local faster-whisper in 512 MB | `app/workers.py:75`, `src/research/voice_stt.py` |

### 1.2 Already shipped — keep green (do not rebuild)

- [x] SHA-256 `content_hash` + `(workspace_id, content_hash)` upload dedup
- [x] arq `_job_id` pinning for duplicate concurrent uploads
- [x] Failed-job listing and manual retry endpoint
- [x] `max_tries` retry policy on the arq worker
- [x] LangGraph checkpoint persistence via asyncpg (`langgraph_checkpoints`)
- [x] Semantic cache packed `float32` vectors (no latin-1 string conversion)
- [x] Cohere rerank applied to retrieval candidates
- [x] Hybrid dense + FTS retrieval with RRF
- [x] Parent-context attachment for selected chunks
- [x] Prompt-safety scanners (secrets, injection phrases, system-prompt leaks)
- [x] Untrusted-document delimiters around retrieved content
- [x] HS256 JWT workspace scoping
- [x] Retrieval golden-set + answer evaluation harness
- [x] Model gateway with Groq → OpenRouter fallback and circuit breaker

**Rule for this plan:** every `[ ]` item below is a verified gap. Items marked
`[x]` are regression-protected, not re-implemented.

---

## 2. Phase 0 — Baseline and guardrails (Day 1)

Do this before changing behavior, so every later change has a before/after.

- [ ] Record a baseline scorecard from the existing harness
      (`apps/api/scripts/eval/run_eval.py`) and commit it as
      `apps/api/tests/fixtures/eval/baseline_v1.json`
- [ ] Capture baseline p50/p95 latency and token counts for 10 representative
      questions (single-hop, multi-hop, unanswerable)
- [ ] Record container RSS at idle, during PDF ingestion, and during a voice
      session (`docker stats` or `docker run --memory=512m`)
- [ ] Turn the non-blocking CI eval job into a **blocking** gate once the
      baseline is committed (`.github/workflows/ci.yml`)
- [ ] Add a `docs/adr/` index entry for any new dependency introduced below
      (repo rule: no dependency without an ADR)

**Exit criteria:** baseline JSON + RSS numbers exist in the repo and CI
reports a comparable score on every PR.

---

## 3. Phase 1 — Stop production failure modes (Days 1–4)

### 3.1 Memory isolation (P0)

- [ ] Add `WORKER_MAX_JOBS` setting (default `1` for the 512 MB tier)
- [ ] Set `WorkerSettings.max_jobs = settings.WORKER_MAX_JOBS`
- [ ] Update `tests/ingestion/test_backpressure.py` which currently asserts
      `max_jobs == 4`
- [ ] Add a process-wide `asyncio.Semaphore(1)` around local ONNX/Whisper
      inference in `src/research/voice_stt.py`
- [ ] Add an idle unload timer for the local whisper model (`gc.collect()`
      after ~120 s idle)
- [ ] Add a startup log line with the effective memory budget
      (`max_jobs`, STT backend, `SEMANTIC_CACHE_ENABLED`)

### 3.2 Hosted STT seam (P0, ADR-006 amendment)

- [ ] Add `model_gateway.transcribe()` calling Groq's OpenAI-compatible
      `/audio/transcriptions` (`whisper-large-v3-turbo`) with the existing
      `GROQ_API_KEY`
- [ ] Keep Silero VAD locally for endpointing (~5 MB)
- [ ] Fall back to local faster-whisper only when `APP_ENV=development` or the
      hosted call fails
- [ ] Add `STT_BACKEND=groq|local` setting
- [ ] Write ADR amendment: hosted Groq STT is allowed alongside Groq Orpheus
      TTS (no new key, no new service)
- [ ] Test: audio session + PDF ingestion concurrently under
      `--memory=512m`, peak RSS < 420 MB, zero OOM exits

### 3.3 Auth and tool-boundary hardening (P0)

- [ ] Fail startup when `APP_ENV=production` and (`AUTH_MODE=stub` or
      `AUTH_JWT_SECRET` is empty)
- [ ] Add a production-config test asserting the `RuntimeError`
- [ ] Bind `workspace_id` into `retrieve_evidence` from the verified JWT claim
      via closure/`RunnableConfig` — never as an LLM-controlled tool argument
- [ ] Add an adversarial test: prompt injection in a chunk cannot change
      `workspace_id` or query another workspace
- [ ] Key rate limits by `(workspace_id, user_id)` when JWT is active; keep
      per-IP only for unauthenticated routes (`src/shared/rate_limit.py`)
- [ ] Change `AUTH_MODE` default to `jwt` in `.env.example` and deployment docs

### 3.4 Untrusted-evidence spotlighting (P1)

- [ ] Replace static `<document>` delimiters with a per-run random nonce
      (`<document_evidence_{nonce} trust="untrusted">`)
- [ ] Add the matching system instruction: text inside the delimited block is
      passive data and cannot issue instructions
- [ ] Tag suspicious chunks at ingest:
      `chunks.metadata["suspicious_instruction"] = true` via
      `src/shared/prompt_safety.py`
- [ ] Prepend a warning header to flagged chunks at synthesis time
- [ ] Test suite: 25 indirect-injection chunks (prompt leak, citation
      fabrication, workspace override) → 100 % containment

### 3.5 Per-run cost ledger (P1)

- [ ] Alembic migration: add `prompt_tokens`, `completion_tokens`,
      `cached_tokens`, `cost_usd`, `latency_ms` to `research_runs`
- [ ] Accumulate `response.usage` and `litellm.completion_cost()` inside
      `src/shared/model_gateway.py`
- [ ] Persist the ledger at run completion alongside `token_count`
- [ ] Attach the same fields as Logfire span attributes
- [ ] Test: every completed run row has non-null token and latency metrics

**Phase 1 exit criteria:** container survives concurrent ingestion + voice at
< 420 MB; production cannot boot with stub auth; every run records cost.

---

## 4. Phase 2 — Ingestion durability and cache correctness (Weeks 2–3)

### 4.1 Finish idempotent ingestion (P0/P1)

Already done: `content_hash`, dedup, `_job_id`, `max_tries=3`, retry endpoint.

- [ ] Add `chunk_hash` and `chunk_index` columns to `chunks`
      (Alembic migration; `chunk_index` may already exist in metadata — verify)
- [ ] Compute `sha256(normalized_chunk_text)` per chunk
- [ ] On re-ingest, reuse existing embeddings for unchanged `chunk_hash` and
      send only new/changed chunks to Cohere
- [ ] Add exponential backoff to arq retries (`Retry(defer=...)`)
- [ ] Add explicit `failed_dlq` stage on `IngestionJob` with `last_error` and
      `attempt_count`
- [ ] Ensure stage transitions are transactional:
      `async with session.begin():` around chunk replacement + document status
- [ ] Use deterministic B2 key `ws/{workspace_id}/sha256/{file_hash}` so a
      failed commit never orphans a second object
- [ ] Tests:
      - [ ] duplicate upload → 1 document row, 1 arq job, 1 embed batch
      - [ ] 1-paragraph edit in a 10-chunk doc → only changed chunk embedded
      - [ ] Cohere 503 on attempt 1 → succeeds on attempt 2, `attempt_count=2`
      - [ ] persistent failure ×4 → `stage=failed_dlq`, `last_error` populated
      - [ ] 10 parallel identical uploads → `COUNT(*) = 1`

### 4.2 Semantic cache hardening (P1, ADR-007 amendment)

- [ ] Include a conversation-context fingerprint in the exact key for
      multi-turn requests: `scache:eq:{ws}:{context_hash}:{query_hash}`
- [ ] Context fingerprint = last assistant turn's cited `document_id`s +
      normalized prior-question hash (no extra LLM call)
- [ ] On store, extract cited `document_id`s and
      `SADD scache:doc:{ws}:{doc_id} {entry_id}`
- [ ] On `DELETE /api/ingestion/documents/{id}`, evict only entries in that
      document's set instead of `invalidate_workspace()`
- [ ] Keep a workspace-wide flush as an explicit admin/rebuild path only
- [ ] Tests:
      - [ ] adversarial follow-up ("What is their revenue?" after two entity
            turns) → 0 false cache hits
      - [ ] semantic lookup = 2 Redis round-trips on hit, 1 on miss
      - [ ] deleting doc A preserves cached answers that only cite doc B

**Phase 2 exit criteria:** zero duplicate embedding spend on re-upload;
transient failures self-heal; no cross-conversation cache collisions.

---

## 5. Phase 3 — Retrieval quality engine (Weeks 2–4)

### 5.1 Contextual chunk headers (P1)

- [ ] In `src/ingestion/chunker.py`, extract structure (PDF headings, Markdown
      AST headers, tree-sitter module/class/function scope)
- [ ] Prepend `[Doc: {filename} | Section: {breadcrumb}]\n{chunk_text}` before
      computing the embedding and `tsvector`
- [ ] Store the header separately in metadata so it can be excluded from
      display/citation text
- [ ] Keep the token overhead bounded (~5–8 %)
- [ ] Test: a chunk inside a financial PDF retains its document + section in
      both embedding input and FTS terms

### 5.2 Single-CTE hybrid search (P1)

Current path makes 3 round-trips and pulls every workspace chunk id into
Python (`_get_workspace_chunk_ids`). Replace it.

- [ ] Verify indexes exist: `USING hnsw (embedding vector_cosine_ops)` on
      `chunks.embedding`, GIN on `chunks.tsv`, btree on
      `(document_id, chunk_index)`
- [ ] Replace `_hybrid_search` with one parameterized SQL CTE:
      `prefilter` → `dense` (`ORDER BY embedding <=> :q_vec LIMIT 30`) →
      `lexical` (`ts_rank_cd(tsv, websearch_to_tsquery('english', :q_text))`
      `LIMIT 30`) → `rrf` (`FULL OUTER JOIN`, `w_d/(60+rank_d) + w_l/(60+rank_l)`)
      → top 25
- [ ] Use `websearch_to_tsquery`, never `to_tsquery`, so raw punctuation cannot
      raise a SQL syntax error
- [ ] Remove the Python allowlist query from the hot path (workspace scoping
      moves into the CTE)
- [ ] Add `EXPLAIN ANALYZE` assertions in a test: Index Scan on HNSW and GIN
- [ ] Benchmark: candidate generation < 80 ms p95, 1 SQL round-trip

### 5.3 Reranker gate, abstention, neighbor expansion (P1)

- [ ] Add `τ_keep = 0.20` and `τ_abstain = 0.35` as settings
- [ ] Drop candidates below `τ_keep`
- [ ] Short-circuit to a deterministic abstention answer when the best score
      across all iterations is below `τ_abstain`
- [ ] For the top `K = 6`, fetch `chunk_index ± 1` in one batch query and merge
      contiguous spans
- [ ] Enforce a hard token budget per merged span (e.g. 600 tokens)
- [ ] Degrade gracefully on Cohere timeout/5xx: use RRF order and mark
      `reranker_degraded=true` on the span
- [ ] Tune `τ_abstain` on the golden set; over-abstention on answerable
      queries must stay < 5 %
- [ ] Test: unanswerable bucket abstains cleanly; answerable buckets do not

### 5.4 Claim verifier (P1, supersedes LLM Critic/Confidence Scorer)

- [ ] Add `src/research/verifier.py`
- [ ] Parse the draft answer into `(claim_sentence, [cited_chunk_ids])`
- [ ] Deterministic ID check: flag/strip any citation not returned by
      `retrieve_evidence` in this run
- [ ] Batched entailment check: one Cohere Rerank v3 call over all cited
      `(claim, chunk_text)` pairs (or cached-embedding cosine fallback)
- [ ] If a claim scores below `τ_ground = 0.30` and iterations < 5, trigger one
      targeted corrective retrieval pass
- [ ] Persist verification outcomes on the run (counts + degraded flag)
- [ ] Tests: fabricated chunk id, swapped citation, unsupported numeric claim
- [ ] Do **not** add separate Critic / Confidence Scorer / Self-Correction
      nodes; document this supersession in `docs/specs/researcher.md`

**Phase 3 exit criteria:** ≥ +5 % relative NDCG@5, 0 % phantom citations,
claim verification < 200 ms with 0 extra LLM tokens.

---

## 6. Phase 4 — Agent runtime and routing (Weeks 4–5)

### 6.1 Tiered model routing (P1)

- [ ] Add `role: Literal["router", "researcher", "synthesizer"]` to
      `complete()` / `complete_with_tools()` / `complete_stream()`
- [ ] Route `router` to `groq/llama-3.1-8b-instant`
- [ ] Route `synthesizer` to `groq/llama-3.3-70b-versatile` with OpenRouter
      fallback
- [ ] On router tool-schema validation failure, retry once on the 70B model
- [ ] Preserve the existing Groq → OpenRouter fallback chain and circuit
      breaker
- [ ] Benchmark quality delta; reject if citation precision drops > 2 %

### 6.2 Multi-query tool fan-out (P2)

- [ ] Extend the `retrieve_evidence` tool schema with
      `sub_queries: list[{semantic_query, keyword_terms}]` (max 3)
- [ ] Execute sub-queries concurrently with `asyncio.gather()`
- [ ] Deduplicate chunks by `chunk_id` before one batched rerank pass
- [ ] Keep `len(sub_queries) == 1` as the simple-query path
- [ ] Do **not** add a separate Query Decomposer node
- [ ] Target: multi-hop questions resolve in ≤ 2 ReAct iterations

### 6.3 Append-only prompt prefix + chunk dedup (P1)

- [ ] Enforce strictly append-only message history:
      `[system + tools] → [history] → [question] → [tool call/output]*`
- [ ] Never reorder or mutate earlier messages mid-run
- [ ] Deduplicate `chunk_id`s across iterations so iteration 3 never re-appends
      a chunk from iteration 1
- [ ] Test: multi-iteration run contains no duplicate `chunk_id` payloads

### 6.4 Resumable streams + checkpoint hygiene (P2)

- [ ] Emit a deterministic `run_id` in the initial AG-UI `RUN_STARTED` event
- [ ] Tee SSE events into a Redis Stream `stream:run:{run_id}` with
      `MAXLEN ~ 200` and a 600 s TTL
- [ ] Add `GET /api/research/runs/{run_id}/stream?last_event_id=...` to replay
      missed events or resume from the last committed checkpoint
- [ ] Wire `@tanstack/ai-persistence` on the frontend (ADR-005)
- [ ] Add a checkpoint cleanup task (worker startup or arq cron) deleting raw
      checkpoints older than 48 h; keep permanent `research_runs` / `citations`
- [ ] Test: kill a run after iteration 2, resume, assert no duplicate Cohere or
      Groq calls

**Phase 4 exit criteria:** p50 latency down ≥ 20 % on multi-hop; 70B token
spend down ≥ 25 %; a refreshed tab never restarts a completed iteration.

---

## 7. Phase 5 — Evaluation harness and CI gate (Weeks 4–5)

### 7.1 Tier 1 — deterministic gate (every PR, < 15 s, $0)

- [ ] Retrieval MRR@10 / NDCG@5 / Recall@10 on the cached golden set
- [ ] RRF ablation (dense-only vs lexical-only vs fused)
- [ ] Cross-workspace isolation assertions (ADR-008)
- [ ] Guardrail redaction + injection containment assertions (ADR-010)
- [ ] Citation structural integrity: every `[cite_id]` maps to a chunk returned
      in the run
- [ ] Block merge if NDCG@5 drops > 1 % or any isolation test fails

### 7.2 Tier 2 — agentic benchmark (on demand / pre-release)

- [ ] Build `tests/eval/golden_dataset_v1.jsonl` with 60 cases across a fixed
      15-document corpus
- [ ] Bucket A — single-hop precision (20)
- [ ] Bucket B — multi-hop / cross-section synthesis (15)
- [ ] Bucket C — contextual ambiguity + 2-turn follow-ups (10)
- [ ] Bucket D — unanswerable / abstention (10)
- [ ] Bucket E — adversarial + cross-workspace isolation (5)
- [ ] Add `scripts/run_eval_suite.py` producing a versioned Markdown + JSON
      scorecard
- [ ] Metrics: citation precision/recall, answer faithfulness, abstention F1,
      iteration efficiency, p50/p95 latency, tokens and USD per answer

### 7.3 Acceptance thresholds

| Metric | Threshold |
|---|---|
| NDCG@5 (relative) | ≥ +5 %, no regression on Bucket A |
| Citation precision | ≥ 0.88 |
| Citation recall | ≥ 0.85 |
| Valid citation IDs | 100 % |
| Faithfulness (A/B/C) | ≥ 0.92 |
| Abstention F1 (D) | ≥ 0.85 |
| p50 / p95 total run | < 4.5 s / < 12 s |
| Retrieval CTE p95 | < 80 ms |
| 70B input tokens (multi-iteration) | ≥ 25 % reduction |
| Peak RSS (512 MB limit) | < 420 MB |
| Cross-workspace leaks | 0 |

---

## 8. Ablation Matrix

Hold `temperature=0.0` and seeds fixed. Run the 60-case benchmark across five
configurations.

| Config | Change | What it isolates |
|---|---|---|
| 0 | Baseline: flat chunks, current hybrid, single 70B, no gate | Reference |
| 1 | + contextual headers + neighbor window | Retrieval delta |
| 2 | + single-CTE SQL + reranker gate (`τ_abstain ∈ {0.25,0.30,0.35,0.40}`) | Latency + abstention F1 |
| 3 | + multi-query fan-out + 8B/70B routing | Multi-hop recall, iterations, cost |
| 4 | + claim verifier | Citation precision vs. overhead |

**Rollback conditions — feature-flag off immediately if:**

- Citation precision or faithfulness drops > 2 % on Buckets A/B
- `τ_abstain` causes > 5 % abstention on answerable queries
- Corrective loops add > 2.5 s to p95
- Groq 429 fallbacks occur on > 5 % of benchmark runs

---

## 9. Three Portfolio Projects (bundled deliverables)

### Project 1 — Contextual Hybrid Retrieval & Cross-Encoder Verification

- [ ] Contextual breadcrumb chunker (§5.1)
- [ ] Single-CTE hybrid RRF engine (§5.2)
- [ ] Parent/neighbor expander + calibrated reranker gate (§5.3)
- [ ] Deterministic + cross-encoder claim verifier (§5.4)
- [ ] `EXPLAIN ANALYZE` index assertions + ablation benchmark

**Outcome:** 1 DB round-trip, ≥ +8 % NDCG@5, 0 % phantom citations,
< 200 ms verification, 0 extra LLM tokens.

### Project 2 — Fault-Tolerant Ingestion & Memory-Bounded Worker

- [ ] Streaming SHA-256 dedup (done) + delta chunk indexing (§4.1)
- [ ] Staged, checkpointed arq pipeline + DLQ + replay endpoint (§4.1)
- [ ] Provenance-aware cache invalidation (§4.2)
- [ ] 512 MB memory guard + hosted STT gateway (§3.1–3.2)
- [ ] Chaos tests (429/503 injection) + 10× concurrent upload race test

**Outcome:** 0 OOM kills at `--memory=512m`, 0 duplicate embedding spend,
transient failures recover without manual intervention.

### Project 3 — Durable Agent Runtime, Cost Ledger & Eval Harness

- [ ] Checkpointed LangGraph runtime (done) + TTL cleanup (§6.4)
- [ ] Resumable AG-UI SSE buffer (§6.4)
- [ ] Tiered router + append-only prefix optimization (§6.1, §6.3)
- [ ] Per-run cost/latency ledger (§3.5)
- [ ] Two-tier evaluation suite + CI gate (§7)

**Outcome:** p50 latency and 70B spend down ≥ 25 % with zero citation-precision
regression; every run has a cost and latency record.

---

## 10. Execution Order (what to do first)

1. **Phase 0 baseline** — without it, no later claim is measurable.
2. **Phase 1.1–3.3** — OOM, auth bypass, and cost visibility are production
   risks, not optimizations.
3. **Phase 2.1** — finish ingestion durability before re-indexing the corpus
   with contextual headers (otherwise you burn Cohere quota on every
   experiment).
4. **Phase 3** — retrieval quality, measured against the baseline.
5. **Phase 4** — routing and resumability, only after quality is stable.
6. **Phase 5** — lock everything behind the blocking gate.

**Do not start** Planner, Critic, Confidence Scorer, Self-Correction, MCP
tools, or self-hosted vLLM/SGLang. They are explicitly out of MVP scope
(`docs/PRD.md` Non-Goals) and unjustified at current volume. Revisit
self-hosting only above ~15 M tokens/day or under a data-residency requirement;
the `model_gateway` seam already makes that a config change.

---

## 11. Definition of Done (release gate)

- [ ] All P0 items complete; no `[ ]` remains in Phases 1–2
- [ ] `uv run pytest` green, including new reliability and injection tests
- [ ] `uv run ruff check .` and `uv run basedpyright` clean
- [ ] Container survives concurrent PDF ingestion + live voice query under
      `--memory=512m` with peak RSS < 420 MB
- [ ] CI blocks on Tier 1 eval regression and isolation failures
- [ ] Tier 2 scorecard committed and meets §7.3 thresholds
- [ ] ADR amendments recorded for ADR-006 (hosted STT) and ADR-007 (cache
      keying/eviction)
- [ ] `docs/latest-architecture.html` nodes `idem`, `dlq`, `ckpt`, `cost`,
      `evals` updated from planned to implemented
- [ ] `docs/REMAINING.md` status table updated to match shipped code

---

## 12. References

- `docs/PRD.md` — MVP scope and Non-Goals
- `docs/adr/ADR-001-langgraph.md`, `ADR-003-model-gateway.md`,
  `ADR-006-voice-agent.md`, `ADR-007-semantic-cache.md`,
  `ADR-008-jwt-auth.md`, `ADR-010-guardrails.md`
- `docs/specs/ingestion.md`, `docs/specs/retrieval.md`,
  `docs/specs/researcher.md`, `docs/specs/evaluation.md`,
  `docs/specs/semantic-cache.md`
- `docs/latest-architecture.html` — gap nodes `idem`, `dlq`, `ckpt`, `cost`,
  `evals`
- `apps/api/src/ingestion/router.py`, `apps/api/src/ingestion/pipeline.py`,
  `apps/api/src/retrieval/pipeline.py`,
  `apps/api/src/shared/model_gateway.py`,
  `apps/api/src/shared/semantic_cache.py`,
  `apps/api/src/research/checkpoint.py`
