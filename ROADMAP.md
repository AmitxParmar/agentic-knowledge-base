# Roadmap — Agentic Knowledge Base

> **Status as of now:** All code scaffolding is written. Nothing runs yet.
> The goal of this document is to get from *code written* to *ask a question,
> get a cited answer* as fast as possible, then plan what comes after.

---

## What Is Already Built

| File | What it does |
|---|---|
| `app/settings.py` | All env vars, pydantic-settings, Groq + Open1 config |
| `app/main.py` | FastAPI factory, lifespan, CORS, router mounts |
| `src/shared/model_gateway.py` | Groq → OpenRouter fallback, `complete()` + `complete_with_tools()` |
| `src/shared/database.py` | Async SQLAlchemy engine, `get_session` dep |
| `src/shared/errors.py` | Domain error hierarchy + FastAPI exception handlers |
| `src/shared/progress.py` | `IngestionStage` / `ResearchStage` enums, `emit()` over WS |
| `src/observability/setup.py` | Logfire + Langfuse wiring, one `configure()` call |
| `src/auth/models.py` | `User`, `Workspace` ORM models |
| `src/auth/stub.py` | MVP auth stub, hardcoded dev workspace/user UUIDs |
| `src/ingestion/models.py` | `Document`, `IngestionJob`, `Chunk` ORM models |
| `src/ingestion/extractors.py` | Docling / faster-whisper / gitingest+tree-sitter wrappers |
| `src/ingestion/chunker.py` | Chonkie `SemanticChunker` + `CodeChunker` |
| `src/ingestion/pipeline.py` | 6-stage arq job: extract → chunk → embed → persist |
| `src/ingestion/router.py` | `POST /api/ingestion/upload`, `GET /api/ingestion/jobs/{id}` |
| `src/retrieval/embedder.py` | BGE-M3 + BGE-Reranker httpx clients |
| `src/retrieval/vector_index.py` | Turbovec wrapper (numpy fallback for dev) |
| `src/retrieval/pipeline.py` | HyDE → hybrid search (dense + BM25 + RRF) → rerank |
| `src/research/models.py` | `ResearchRun`, `Citation` ORM models |
| `src/research/agent.py` | LangGraph `StateGraph` ReAct agent, citation-at-retrieval |
| `src/research/router.py` | `WS /api/research/ws` + `GET /api/research/runs/{id}` |
| `alembic/env.py` | Async Alembic env, imports all models for autogenerate |

---

## Core Pipeline Plan — Get It Testable

Ordered by dependency. Each step unblocks the next. Target: upload a PDF,
ask a question, receive a cited answer.

---

### Step 1 — Fix Import Paths (30 min)

The generated code uses `from apps.api.app.settings import settings`.
Since `uv run` executes from `apps/api/`, the correct import is
`from app.settings import settings`.

- [*] Global find-replace `from apps.api.app.settings` → `from app.settings`
- [*] Global find-replace `from apps.api.app` → `from app`
- [*] Verify `src/` is on the path: add `pythonpath = [".", "src"]` to
      `pyproject.toml` under `[tool.pytest.ini_options]` and confirm
      `uv run python -c "from src.shared.database import Base"` works from `apps/api/`
- [*] Move worker from `apps/worker/main.py` → `app/worker.py` so it shares
      the same venv and imports. Update start command to
      `uv run arq app.worker.WorkerSettings`

### Step 2 — Project Config Files (30 min)

These files are referenced in `AGENTS.md` but not yet created.

- [*] `apps/api/pyrightconfig.json` — basedpyright config pointing at `src/` and `app/`
- [ ] `apps/api/alembic.ini` — points `script_location = alembic`, overrides URL from settings
- [ ] `apps/api/alembic/script.py.mako` — default migration template
- [ ] Confirm `uv run alembic --help` works from `apps/api/`

**`pyrightconfig.json` (minimal):**
```json
is moved to the root directory of this monorepo to compatibly run with the IDE.
```

### Step 3 — Services Up (30 min)

Create `apps/api/infra/docker-compose.yml`:
we will use real serverless redis and neondb postgres urls in the .env so avoid this docker services for now 

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: research_workspace
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports: ["5432:5432"]
    volumes: [postgres_data:/var/lib/postgresql/data]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

volumes:
  postgres_data:
```

- [ ] `docker compose up -d` — Postgres + Redis running
- [ ] `uv run python -c "import asyncpg; print('asyncpg ok')"` from `apps/api/`
- [ ] Confirm `.env` has correct `DATABASE_URL` and `REDIS_URL`

### Step 4 — Database Migration (20 min)

- [ ] `uv run alembic revision --autogenerate -m "initial"` — review generated SQL
- [ ] Open the generated migration file, add the tsvector column + GIN index manually:
  ```python
  # Inside upgrade():
  op.execute("ALTER TABLE chunks ADD COLUMN tsv tsvector")
  op.execute("CREATE INDEX chunks_tsv_idx ON chunks USING GIN(tsv)")
  op.execute("""
      CREATE OR REPLACE FUNCTION chunks_tsv_update() RETURNS trigger AS $$
      BEGIN
        NEW.tsv := to_tsvector('english', NEW.text);
        RETURN NEW;
      END $$ LANGUAGE plpgsql
  """)
  op.execute("""
      CREATE TRIGGER chunks_tsv_trigger
      BEFORE INSERT OR UPDATE ON chunks
      FOR EACH ROW EXECUTE FUNCTION chunks_tsv_update()
  """)
  ```
- [ ] `uv run alembic upgrade head` — all tables created
- [ ] `psql -U postgres research_workspace -c "\dt"` — confirm all 7 tables exist

### Step 5 — Seed Dev Data (10 min)

Create `apps/api/scripts/seed.py`:

```python
# Creates the dev User + Workspace matching auth/stub.py hardcoded UUIDs
# Run: uv run python scripts/seed.py
import asyncio, uuid
from sqlalchemy.ext.asyncio import AsyncSession
from src.shared.database import SessionLocal
from src.auth.models import User, Workspace

DEV_USER_ID    = uuid.UUID("00000000-0000-0000-0000-000000000002")
DEV_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

async def seed():
    async with SessionLocal() as s:
        s.add(User(id=DEV_USER_ID, email="dev@local", name="Dev User"))
        s.add(Workspace(id=DEV_WORKSPACE_ID, owner_id=DEV_USER_ID, name="Dev Workspace"))
        await s.commit()
        print("seeded")

asyncio.run(seed())
```

- [ ] `uv run python scripts/seed.py` — confirm no FK errors

### Step 6 — Test Model Gateway (15 min)

This is the fastest way to verify API keys before anything else.

- [ ] Set `MODEL_GATEWAY_GROQ_API_KEY` in `.env`
- [ ] `uv run pytest tests/test_model_gateway.py -v` — provider chain tests pass
- [ ] Quick smoke: `uv run python -c "import asyncio; from src.shared.model_gateway import complete; print(asyncio.run(complete([{'role':'user','content':'say hi'}])))"`
- [ ] Blank the Groq key temporarily → confirm OpenRouter fallback fires (check logs)

### Step 7 — BGE Services (1 hour)

Two options — pick whichever matches your setup:

**Option A — Hugging Face Text Embeddings Inference (recommended):**
```yaml
# Add to docker-compose.yml
bge-embedder:
  image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.5
  command: --model-id BAAI/bge-m3 --port 8001
  ports: ["8001:8001"]

bge-reranker:
  image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.5
  command: --model-id BAAI/bge-reranker-v2-m3 --port 8002
  ports: ["8002:8002"]
```
Note: TEI uses `/embed` and `/rerank` endpoints — matches `embedder.py` exactly.

**Option B — Local Python server (simpler, slower):**
- [ ] Create `apps/api/scripts/bge_server.py` — minimal FastAPI wrapping
      `sentence-transformers` for `/embed` and `/rerank`
- [ ] `uv run python scripts/bge_server.py --port 8001 --model bge-m3`

Either way:
- [ ] `curl http://localhost:8001/embed -d '{"texts":["hello"]}' -H 'Content-Type: application/json'` returns a vector
- [ ] `curl http://localhost:8002/rerank -d '{"query":"test","passages":["a","b"]}' -H 'Content-Type: application/json'` returns scores
- [ ] `uv run python -c "import asyncio; from src.retrieval.embedder import embed_query; print(len(asyncio.run(embed_query('test'))))"` — prints 1024

### Step 8 — Test Ingestion End-to-End (1 hour)

- [ ] `uv run uvicorn app.main:app --reload --port 8000` — server starts, `/health` returns 200
- [ ] `uv run arq app.worker.WorkerSettings` — worker starts in a second terminal
- [ ] Upload a small PDF (< 5 pages):
  ```bash
  curl -X POST http://localhost:8000/api/ingestion/upload \
    -F "file=@test.pdf" \
    -F "source_type=pdf"
  ```
- [ ] Note the `document_id` and `job_id` from response
- [ ] Poll status: `curl http://localhost:8000/api/ingestion/jobs/{job_id}` — watch stage advance
- [ ] Confirm final stage is `done` (not `failed`)
- [ ] Check DB: `SELECT count(*) FROM chunks WHERE document_id = '...'` — non-zero
- [ ] Check tsv: `SELECT tsv IS NOT NULL FROM chunks LIMIT 1` — should be true
- [ ] Check vector index: add a debug print in `vector_index.py` to confirm upsert count

### Step 9 — Test Retrieval (30 min)

- [ ] Create `apps/api/scripts/test_retrieval.py`:
  ```python
  import asyncio, uuid
  from src.shared.database import SessionLocal
  from src.retrieval.pipeline import retrieve

  async def main():
      ws_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
      async with SessionLocal() as session:
          results = await retrieve("what is this document about?", ws_id, session)
          for r in results:
              print(f"[{r.relevance_score:.3f}] {r.source_ref}: {r.chunk_text[:80]}")

  asyncio.run(main())
  ```
- [ ] `uv run python scripts/test_retrieval.py` — should print ranked chunks
- [ ] Verify: results are scoped to the dev workspace (no cross-workspace leakage)
- [ ] Verify: every result has `chunk_id`, `document_id`, `source_ref` populated

### Step 10 — Test Research Agent (30 min)

- [ ] Create `apps/api/scripts/test_agent.py`:
  ```python
  import asyncio, uuid
  from src.shared.database import SessionLocal
  from src.research.agent import run_agent

  async def main():
      ws_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
      run_id = uuid.uuid4()
      async with SessionLocal() as session:
          result = await run_agent(
              question="Summarise the main points of the uploaded document.",
              workspace_id=ws_id,
              run_id=run_id,
              session=session,
          )
          print("ANSWER:", result.answer)
          print("CITATIONS:", len(result.citations))
          for c in result.citations:
              print(f"  [{c['source_ref']}]")

  asyncio.run(main())
  ```
- [ ] `uv run python scripts/test_agent.py` — answer printed, citations > 0
- [ ] Confirm `research_runs` row exists in DB with `status = complete`
- [ ] Confirm `citations` rows exist with valid `chunk_id` FKs
- [ ] Check Langfuse dashboard — trace visible for the run

### Step 11 — Test WebSocket End-to-End (30 min)

- [ ] Install `wscat` or use a browser WebSocket client
- [ ] Connect: `wscat -c ws://localhost:8000/api/research/ws`
- [ ] Send: `{"question": "What does the document say about X?"}`
- [ ] Verify messages arrive in order:
  1. `{"type": "progress", "stage": "Searching documents..."}`
  2. `{"type": "progress", "stage": "Reviewing evidence..."}`
  3. `{"type": "progress", "stage": "Generating report..."}`
  4. `{"type": "progress", "stage": "Finalizing answer..."}`
  5. `{"type": "answer", "text": "...", "citations": [...]}`
  6. `{"type": "done"}`
- [ ] Verify no chain-of-thought, prompt text, or tool payloads in any message
- [ ] Kill the connection mid-run — verify `ResearchRun.status` becomes `failed`

### Step 12 — Typecheck + Lint (20 min)

- [ ] `uv run ruff check .` — zero errors
- [ ] `uv run ruff format --check .` — zero formatting issues
- [ ] `uv run basedpyright` — zero type errors (fix any `# type: ignore` left over)
- [ ] `uv run pytest tests/ -v` — all tests pass

---

## ✅ Definition of Done (Core Pipeline)

The knowledge base is testable when all of these are true without manual intervention:

- PDF upload → `done` status in < 60s for a 10-page doc
- Question → cited answer via WebSocket
- Every answer has ≥ 1 citation with a clickable `source_ref`
- Progress events arrive in `ux.md` vocabulary order
- `ruff check` and `basedpyright` pass clean

---

## Future Plan

These ship in priority order after the core pipeline is verified with real usage.

---

### F1 — Minimal Frontend (Next.js) — *Unblock non-technical testing*

Without this, only curl/wscat can test the system.

- [ ] Upload component: file picker + source type selector → `POST /api/ingestion/upload`
- [ ] Ingestion progress: poll `GET /api/ingestion/jobs/{id}` → show stage badges
- [ ] Chat input: text box → connect WebSocket on submit
- [ ] Progress stream: render each stage event as a status pill
- [ ] Answer display: markdown render of answer text
- [ ] Citation list: numbered refs below the answer, each linking to source chunk
- [ ] Error state: surface `{"type": "error"}` messages to user

---

### F2 — Production Hardening — *Before any real users*

- [ ] `pyrightconfig.json` strict mode — catch all remaining type gaps
- [ ] Integration test: upload PDF → ask → assert citations non-empty (uses test DB)
- [ ] Ingestion retry logic: arq job retries up to 3× on transient errors
- [ ] BGE health check at startup — fail fast if embedder/reranker unreachable
- [ ] `GET /health` expanded: check DB connection + Redis + BGE endpoints
- [ ] File size limit on upload (reject > 50MB before processing)
- [ ] Accepted file type validation (reject non-PDF/audio/zip at upload)
- [ ] Rate limiting on upload + research endpoints (slowapi or similar — needs ADR)
- [ ] Logfire token set in prod `.env` — traces going to cloud, not just console

---

### F3 — Observability Depth — *After first real run in prod*

- [ ] Langfuse trace includes: question, retrieval query, chunk count, final answer length
- [ ] Per-run cost estimate attached to `ResearchRun` (token count × model rate)
- [ ] Slow retrieval alert: log warning when retrieval > 5s
- [ ] Ingestion failure webhook: POST to a Slack/Discord channel on `failed` stage
- [ ] Dashboard: query Langfuse API for p50/p95 latency + citation rate per day

---

### F4 — Critic Agent + Reflection Loop — *After baseline quality is measured*

Requires a spec in `docs/specs/critic.md` before any code.

- [ ] Write `docs/specs/critic.md` — inputs, outputs, success criteria, when to reflect
- [ ] Implement `src/critic/agent.py` — evaluates draft against retrieved evidence
- [ ] Add Critic → Researcher back-edge in LangGraph graph (what ADR-001 was designed for)
- [ ] Extend Circuit Breaker: bound reflection passes + total token cost, not just iterations
- [ ] Test: find a question where reflection measurably improves the answer
- [ ] Evaluate: run 20 golden questions before/after — citation rate must not drop

---

### F5 — Planner Agent — *After Critic is validated*

- [ ] Write `docs/specs/planner.md`
- [ ] Planner decomposes multi-hop questions into sub-tasks
- [ ] Sub-tasks feed the Researcher sequentially or in parallel
- [ ] Plan stored in `plan_cache` table (deferred entity from `schema.md`)
- [ ] Test: a question that requires 3 separate retrievals to answer correctly

---

### F6 — Semantic Cache — *After usage volume exists*

- [ ] ADR for Redis semantic cache (query embedding → cached answer)
- [ ] Cache hit short-circuits retrieval + agent entirely
- [ ] Cache invalidation on document re-ingestion
- [ ] Cache TTL configurable per workspace

---

### F7 — Working Memory — *After multi-session demand observed*

- [ ] `docs/specs/memory.md`
- [ ] `conversation_summaries` + `semantic_memory` tables (already in `schema.md`)
- [ ] Rolling summary injected into Research Agent system prompt
- [ ] Test: "What did I ask earlier?" returns correct prior context

---

### F8 — Multi-Provider Gateway (LiteLLM) — *When second backend is actually needed*

- [ ] ADR-003 revisit: migrate thin interface → LiteLLM as backend
- [ ] Add hosted fallback (OpenAI / Anthropic) for when local model is down
- [ ] Cost tracking per provider per run
- [ ] No agent code changes required — interface stays identical

---

### F9 — RBAC + Multi-Tenant — *When first non-dev user onboards*

- [ ] Replace `auth/stub.py` with real JWT (Clerk or Auth0)
- [ ] Workspace pre-filter becomes a hard security boundary, not just a query filter
- [ ] Input/output guardrails (add when misuse patterns are observed, not before)

---

### F10 — Evaluation Pipeline — *When golden dataset exists from real usage*

- [ ] Collect 50+ real question/answer pairs as golden dataset
- [ ] RAGAS: context recall, context precision on retrieval
- [ ] DeepEval: answer faithfulness, relevance scores
- [ ] Nightly CI eval run — fail build if citation rate drops below baseline
- [ ] Prometheus + Grafana: latency, token cost, citation rate dashboards

---

## Priority Matrix

```
Now          → Steps 1–12 above (core pipeline testable)
Next sprint  → F1 frontend (unblock non-technical testing)
             → F2 hardening (before any real users)
After usage  → F3 observability depth
             → F4 Critic (improve answer quality)
On demand    → F5 Planner, F6 Cache, F7 Memory
When needed  → F8 LiteLLM, F9 RBAC, F10 Eval
```

Rule: nothing in the future plan ships without a production signal
justifying it. Building F5 before F4 is validated is a process violation
per `AGENTS.md`.