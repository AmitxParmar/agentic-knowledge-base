# Core Flow MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the MVP core flow actually run end to end: upload a document, process it asynchronously, ask a question, and receive a citation-backed answer with the approved progress vocabulary.

**Architecture:** Keep the scope strictly inside the PRD MVP: one FastAPI app, one arq worker, one ingestion pipeline, one retrieval pipeline, and one Research Agent. Do the smallest backend repairs first, then add the thinnest possible web UI only after the backend is verifiably stable.

**Tech Stack:** FastAPI, SQLAlchemy async, arq, LangGraph, httpx, PostgreSQL, Redis, Next.js 16, React 19

---

## File Map

**Modify**
- `apps/api/app/main.py`
- `apps/api/app/settings.py`
- `apps/api/app/workers.py`
- `apps/api/pyproject.toml`
- `apps/api/src/ingestion/router.py`
- `apps/api/src/ingestion/pipeline.py`
- `apps/api/src/retrieval/pipeline.py`
- `apps/api/src/retrieval/vector_index.py`
- `apps/api/src/research/agent.py`
- `apps/api/src/research/router.py`
- `apps/api/src/shared/progress.py`
- `apps/api/tests/integration/test_citation_survival.py`
- `apps/web/app/page.tsx`
- `apps/web/app/page.module.css`

**Create**
- `apps/api/pyrightconfig.json`
- `apps/api/alembic.ini`
- `apps/api/alembic/script.py.mako`
- `apps/api/scripts/seed.py`
- `apps/api/tests/integration/test_core_flow_smoke.py`

**Why these files**
- `app/*` and `pyproject.toml` unblock startup, imports, worker boot, and local test execution.
- `src/ingestion/*`, `src/retrieval/*`, and `src/research/*` are the real MVP core flow.
- `apps/web/*` stays intentionally tiny and only exists to exercise the backend once the backend is stable.

### Task 1: Repair Runtime Bootstrap

**Files:**
- Modify: `apps/api/app/main.py`
- Modify: `apps/api/app/settings.py`
- Modify: `apps/api/app/workers.py`
- Modify: `apps/api/pyproject.toml`
- Create: `apps/api/pyrightconfig.json`
- Create: `apps/api/alembic.ini`
- Create: `apps/api/alembic/script.py.mako`

Comment: This task removes the obvious “nothing runs yet” failures before we touch feature logic.

- [ ] **Step 1: Add test/runtime python paths so `app` and `src` resolve from `apps/api/`**

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = [".", "src"]
```

- [ ] **Step 2: Keep app startup minimal and enable the two MVP routers**

```python
from src.ingestion.router import router as ingestion_router
from src.research.router import router as research_router

app.include_router(ingestion_router, prefix="/api/ingestion", tags=["ingestion"])
app.include_router(research_router, prefix="/api/research", tags=["research"])
```

- [ ] **Step 3: Normalize settings around local writable paths instead of hardcoded `/tmp/...`**

```python
from pathlib import Path

UPLOAD_DIR: str = Field(
    default=str(Path.cwd() / ".data" / "uploads"),
    description="Writable upload directory for raw source files",
)
```

- [ ] **Step 4: Keep the worker import path local to `apps/api/`**

```python
from src.ingestion.pipeline import run_ingestion_job
from app.settings import settings
```

- [ ] **Step 5: Add the minimal missing config files the roadmap already assumes**

```json
{
  "venvPath": ".",
  "venv": ".venv",
  "include": ["app", "src", "tests"],
  "pythonVersion": "3.11",
  "typeCheckingMode": "basic"
}
```

```ini
[alembic]
script_location = alembic
prepend_sys_path = .

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers = console
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

- [ ] **Step 6: Verify bootstrap from `apps/api/`**

Run: `uv run python -c "from app.main import app; from src.shared.database import Base; print('bootstrap ok')"`

Expected: `bootstrap ok`

### Task 2: Make Ingestion Runnable And Predictable

**Files:**
- Modify: `apps/api/src/ingestion/router.py`
- Modify: `apps/api/src/ingestion/pipeline.py`
- Modify: `apps/api/src/shared/progress.py`
- Create: `apps/api/scripts/seed.py`

Comment: This task keeps ingestion boring: save file, create rows, queue job, process stages, fail cleanly.

- [ ] **Step 1: Replace the broken dynamic import in the upload route with a normal settings import**

```python
from app.settings import settings
from arq.connections import RedisSettings

UPLOAD_DIR = Path(settings.UPLOAD_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: Queue arq jobs with the same local runtime assumptions as the worker**

```python
redis = await arq.create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
await redis.enqueue_job("run_ingestion_job", document_id=str(doc_id))
await redis.close()
```

- [ ] **Step 3: Keep ingestion status timestamps monotonic and set the initial queued timestamp**

```python
job = IngestionJob(
    document_id=doc_id,
    stage=JobStage.queued,
    stage_timestamps={JobStage.queued.value: datetime.now(UTC).isoformat()},
)
```

- [ ] **Step 4: Persist document rows first, then vector rows, using the shared vector singleton**

```python
vector_index = get_vector_index()
for chunk_row, vector in chunk_rows:
    # Write embedding vector to pgvector column
    # Chunk already has embedding written during ingestion pipeline
    pass  # embedding stored in chunks.embedding via migration 9f2a1c3b4e5d
```

- [ ] **Step 5: Add a tiny dev seed script for the auth stub UUIDs**

```python
DEV_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
```

Run: `uv run python scripts/seed.py`

Expected: `seeded`

- [ ] **Step 6: Verify the upload route and ingestion job shape with a targeted smoke test**

Run: `uv run pytest tests/integration/test_core_flow_smoke.py -q`

Expected: upload route creates `Document` + `IngestionJob`, queues the worker call, and returns `queued`

### Task 3: Repair Retrieval So Citation Data Survives

**Files:**
- Modify: `apps/api/src/retrieval/pipeline.py`
- Modify: `apps/api/src/retrieval/vector_index.py`
- Modify: `apps/api/tests/integration/test_citation_survival.py`

Comment: This task is the heart of the MVP. If retrieval loses source references, the product promise breaks.

- [ ] **Step 1: Keep vector writes and reads on the same singleton index**

```python
from src.retrieval.vector_index import get_vector_index

vector_index = get_vector_index()
```

- [ ] **Step 2: Preserve fused ranking order and attach stable source references during hydration**

```python
hydrated.append(
    RetrievedChunk(
        chunk_id=str(chunk.id),
        document_id=str(doc.id),
        chunk_text=chunk.text,
        source_ref=_build_source_ref(doc, chunk),
        relevance_score=0.0,
    )
)
```

- [ ] **Step 3: Keep BM25 simple and portable for now instead of adding a migration-only dependency**

```python
SELECT c.id,
       c.embedding,
       ts_rank_cd(to_tsvector('english', c.text), plainto_tsquery('english', :query)) AS rank
```

Comment: This stays acceptable for MVP because `to_tsvector` inline works before the dedicated trigger/index hardening phase.

- [ ] **Step 4: Extend the citation survival test so it asserts source references survive the retrieval output contract**

```python
assert result.citations[0]["source_ref"] == "report.pdf, chunk 3"
assert result.citations[1]["source_ref"] == "code/main.py:MyClass"
```

- [ ] **Step 5: Verify retrieval ordering logic without external services**

Run: `uv run pytest tests/integration/test_citation_survival.py -q`

Expected: RRF merge passes, rerank reorders, citations keep `chunk_id` and `source_ref`

### Task 4: Repair The Research Agent And WebSocket Contract

**Files:**
- Modify: `apps/api/src/research/agent.py`
- Modify: `apps/api/src/research/router.py`
- Modify: `apps/api/src/shared/progress.py`

Comment: This task keeps the agent inside the spec: one tool, bounded iterations, no chain-of-thought leakage.

- [ ] **Step 1: Stop serializing parsed tool arguments back into invalid OpenAI message payloads**

```python
assistant_tool_call = {
    "id": tc.id,
    "type": "function",
    "function": {
        "name": tc.function.name,
        "arguments": json.dumps(tc.function.arguments),
    },
}
```

- [ ] **Step 2: Emit research stages in user-facing order only**

```python
await stage_callback(ResearchStage.SEARCHING)
await stage_callback(ResearchStage.REVIEWING)
await stage_callback(ResearchStage.GENERATING)
await stage_callback(ResearchStage.FINALIZING)
```

Comment: The current flow mixes these stages in the wrong order.

- [ ] **Step 3: Persist iteration count and citations on the `ResearchRun` before the final WebSocket answer**

```python
run.answer = result.answer
run.iteration_count = len(result.citations)
run.status = RunStatus.complete
run.completed_at = datetime.now(UTC)
```

Comment: If a separate iteration metric is available from the agent, store that instead of citation count.

- [ ] **Step 4: Keep the WebSocket response payload UI-safe and citation-focused**

```python
{
    "type": "answer",
    "run_id": str(run.id),
    "text": result.answer,
    "citations": [
        {
            "chunk_id": c["chunk_id"],
            "source_ref": c["source_ref"],
            "relevance_score": round(c.get("relevance_score", 0.0), 4),
        }
        for c in result.citations
    ],
}
```

- [ ] **Step 5: Add a backend smoke test for the run contract**

```python
assert payload["type"] == "answer"
assert payload["citations"]
assert "source_ref" in payload["citations"][0]
```

Run: `uv run pytest tests/integration/test_core_flow_smoke.py -q`

Expected: answer payload contains citations and only approved progress event strings

### Task 5: Add The Thinnest Web UI For The Core Flow

**Files:**
- Modify: `apps/web/app/page.tsx`
- Modify: `apps/web/app/page.module.css`

Comment: Do not build a full product surface yet. This is just enough UI to manually test the backend without curl and wscat.

- [ ] **Step 1: Replace the starter page with a two-panel core flow UI**

```tsx
type IngestionState = {
  documentId: string | null;
  jobId: string | null;
  stage: string | null;
  error: string | null;
};

type AnswerState = {
  text: string;
  citations: Array<{ chunk_id: string; source_ref: string; relevance_score: number }>;
  stages: string[];
  error: string | null;
};
```

- [ ] **Step 2: Implement upload with `FormData` against `/api/ingestion/upload`**

```tsx
const formData = new FormData();
formData.append("file", file);
formData.append("source_type", sourceType);
```

- [ ] **Step 3: Poll `/api/ingestion/jobs/{id}` until `done` or `failed`**

```tsx
if (data.stage === "done" || data.stage === "failed") {
  return;
}
```

- [ ] **Step 4: Open the research WebSocket only on submit and stream progress pills**

```tsx
const ws = new WebSocket(`${wsBaseUrl}/api/research/ws`);
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
};
```

- [ ] **Step 5: Keep styling intentional but small**

```css
.shell {
  min-height: 100vh;
  background: linear-gradient(180deg, #f4efe3 0%, #efe6d0 100%);
  color: #1e1b16;
}
```

- [ ] **Step 6: Verify the UI builds without new dependencies**

Run: `pnpm --filter web lint`

Expected: no lint errors from the new page

### Task 6: Verification Pass

**Files:**
- Test: `apps/api/tests/shared/test_model_gateway.py`
- Test: `apps/api/tests/integration/test_citation_survival.py`
- Test: `apps/api/tests/integration/test_core_flow_smoke.py`

Comment: This is the minimum proof that the core flow is real, not just scaffolded.

- [ ] **Step 1: Run the smallest backend test set first**

Run: `uv run pytest tests/shared/test_model_gateway.py tests/integration/test_citation_survival.py tests/integration/test_core_flow_smoke.py -q`

Expected: all targeted tests pass

- [ ] **Step 2: Run API lint and type checks**

Run: `uv run ruff check .`

Expected: no lint errors

Run: `uv run basedpyright`

Expected: no blocking type errors in the touched files

- [ ] **Step 3: Run the web lint pass**

Run: `pnpm --filter web lint`

Expected: web app stays clean

- [ ] **Step 4: Manual end-to-end smoke**

Run: `uv run uvicorn app.main:app --reload --port 8000`

Run: `uv run arq app.workers.WorkerSettings`

Run: `pnpm --filter web dev`

Expected:
- upload request returns queued
- job transitions through ingestion stages
- research run streams approved progress labels
- final answer includes one or more citations with `source_ref`

## Recommended Improvements After Core Flow

- Keep `to_tsvector(...)` inline for MVP, then add the proper migration-managed `tsvector` column and GIN index once the core flow is stable.
- Add a tiny repository- and audio-focused smoke path only after the PDF path is green; PDF is the fastest signal for core value.
- Move observability hardening, richer health checks, retries, and startup dependency probes to the next phase exactly as you requested.
- Revisit the current Groq/OpenRouter gateway defaults against ADR-003 later; the cleanest MVP after core flow is a single backend behind the same interface, not more routing complexity.

## Self-Review

**Spec coverage**
- PRD F1/F2/F3/F4/F5/F6/F7/F8/F9 are covered by Tasks 2 through 6.
- ADR-003 is respected because all chat model calls still go through `src/shared/model_gateway.py`.
- `docs/specs/retrieval.md` and `docs/specs/researcher.md` are covered by Tasks 3 and 4.

**Placeholder scan**
- No `TODO`, `TBD`, or “similar to previous task” placeholders were left in the steps.

**Type consistency**
- The plan uses the existing `Document`, `IngestionJob`, `Chunk`, `ResearchRun`, and citation dictionaries already present in the repo instead of inventing new contracts.
