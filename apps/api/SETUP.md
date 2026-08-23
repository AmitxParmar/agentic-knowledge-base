# Setup Guide

## Prerequisites
- Python 3.11+
- Node 20+ (for Turborepo / Next.js)
- Redis (for arq job queue)
- PostgreSQL

## 1. Install Python deps

```bash
cd apps/api
cp .env.example .env        # fill in API keys
pip install -e ".[dev]"
```

## 2. Configure env vars

Edit `apps/api/.env`:
- Set `MODEL_GATEWAY_GROQ_API_KEY` (get at console.groq.com — free tier is fine)
- Set `MODEL_GATEWAY_OPENROUTER_API_KEY` (get at openrouter.ai — fallback)
- Set `COHERE_API_KEY` + `COHERE_EMBED_MODEL` (`embed-english-v3.0`) + `COHERE_RERANK_MODEL` (`rerank-multilingual-v3.0`)
- Set `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` (required by N3 in prod)
- Leave `LOGFIRE_TOKEN` empty for local dev — logs go to console
- Optional: set `SEMANTIC_CACHE_ENABLED=true` to enable the semantic answer cache (ADR-007; see `docs/specs/semantic-cache.md`)

## 3. Run DB migrations

```bash
cd apps/api
alembic upgrade head
```

## 4. Start services

```bash
# API gateway
uvicorn app.main:app --reload --port 8000

# Async worker (ingestion jobs)
arq apps.worker.main.WorkerSettings

# Embeddings + rerank (Cohere API — keys set in .env)
# COHERE_API_KEY / COHERE_EMBED_MODEL / COHERE_RERANK_MODEL
```

## 5. Lint + test

```bash
ruff check .
ruff format .
pytest
```

## Folder Structure

```
apps/
├── api/        FastAPI gateway (uvicorn)
└── worker/     arq ingestion worker

src/
├── research/   Research Agent (LangGraph) — build next
├── retrieval/  Hybrid search + rerank — build next
├── ingestion/  Upload → chunk → embed pipeline — build next
├── auth/       Stubbed (PRD Non-Goal for MVP)
├── observability/ Logfire + Langfuse wiring
└── shared/     model_gateway, database, errors, progress (used by 2+ modules)

tests/          Mirror of src/ paths
```

## Adding a feature

1. Build it in `src/<feature>/`
2. Add a router in `src/<feature>/router.py`
3. Uncomment the `include_router` line in `apps/api/app/main.py`
4. Write tests in `tests/<feature>/`

## Model Gateway (ADR-003)

Never call Groq/OpenRouter SDKs directly. Always:
```python
from src.shared.model_gateway import complete
answer = await complete(messages=[{"role": "user", "content": "..."}])
```

Fallback chain: Groq → OpenRouter. Switch primary via `MODEL_GATEWAY_PROVIDER` env var.
