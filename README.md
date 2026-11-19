# Agentic Research Workspace

Enterprise **agentic RAG knowledge base**: upload your documents, ask questions, get **citation-backed** answers.

MVP scope is a single **Research Agent** (ReAct) over hybrid retrieval. The frozen V1 design also includes Planner, Critic, semantic cache, and MCP tools — see [`docs/PRD.md`](docs/PRD.md) and [`docs/latest-architecture.html`](docs/latest-architecture.html).

| Layer | What it does |
| --- | --- |
| **Knowledge base** | PDF / repo / audio → extract → chunk → embed → Postgres + vectors |
| **RAG** | HyDE → dense + PostgreSQL FTS hybrid (RRF) → rerank → cite chunks |
| **Agentic** | LangGraph Research Agent: reason → retrieve → draft under an iteration cap |

> **DeviceHub AI extension.** The repository is also the host for DeviceHub AI, an additive IoT/fleet-operations extension that reuses this retrieval and agent stack. The Knowledge Base described here remains independently runnable and is not replaced by DeviceHub work. Design documents live in [`docs/DeviceHub/`](docs/DeviceHub/README.md).

## Monorepo layout

| Path | Role |
| --- | --- |
| `apps/api/` | FastAPI, LangGraph agent, arq ingestion workers (Python) |
| `apps/web/` | Next.js UI — upload, progress, Q&A |
| `apps/docs/` | Docs site (scaffold) |
| `packages/ui/` | Shared React components |
| `docs/` | PRD, ADRs, specs, architecture |

## High-level architecture

MVP path (solid). Deferred V1 pieces are dashed.

```mermaid
flowchart TB
  subgraph Clients
    WEB["Next.js web<br/>upload · chat · citations"]
    CLI["API / CLI / wscat"]
  end

  subgraph Gateway["API Gateway · FastAPI"]
    REST["REST<br/>/api/ingestion/*"]
    CHAT["SSE · AG-UI<br/>/api/research/chat"]
    WS["WebSocket (legacy)<br/>/api/research/ws"]
  end

  subgraph Ingest["Ingestion · arq workers"]
    Q["Redis queue"]
    X["Extract<br/>Docling · whisper · tree-sitter"]
    C["Chunk · Chonkie"]
    E["Embed · Cohere embed-v3"]
  end

  subgraph Retrieval["Retrieval engine"]
    HYDE["Query rewrite · HyDE"]
    HYB["Hybrid search + RRF"]
    RER["Rerank · Cohere rerank-v3"]
  end

  subgraph Agent["Orchestration · LangGraph"]
    RA["Research Agent · ReAct"]
  end

  subgraph Storage
    PG[("PostgreSQL<br/>metadata · chunks · FTS")]
    TV[("pgvector<br/>vectors in Postgres")]
    FS[("File storage<br/>raw uploads")]
  end

  subgraph Models["Model Gateway · ADR-003"]
    MG["complete / complete_with_tools<br/>Groq → OpenRouter"]
  end

  WEB --> REST & CHAT
  CLI --> REST & WS
  REST --> Q --> X --> C --> E
  REST --> FS
  E --> PG & TV
  CHAT --> RA
  RA --> HYDE --> HYB
  HYB --> PG & TV
  HYB --> RER --> RA
  RA --> MG
  HYDE --> MG
```

Interactive V1 diagram (Planner, Critic, cache, security zones): open [`docs/latest-architecture.html`](docs/latest-architecture.html) in a browser.

## Low-level: ingestion

Upload returns immediately; an arq worker makes the document searchable.

```mermaid
sequenceDiagram
  participant UI as Web / curl
  participant API as FastAPI
  participant FS as Upload dir
  participant Redis as Redis · arq
  participant W as Worker
  participant X as Extractors
  participant C as Chunker
  participant E as Embedder
  participant PG as PostgreSQL
  participant TV as Vector index

  UI->>API: POST /api/ingestion/upload
  API->>FS: write raw file
  API->>PG: documents + ingestion_jobs
  API->>Redis: enqueue run_ingestion_job
  API-->>UI: document_id, job_id
  UI->>API: GET /api/ingestion/jobs/{id} (poll)
  W->>PG: extracting
  W->>X: extract by source_type
  W->>PG: chunking
  W->>C: semantic / code chunks
  W->>PG: embedding
  W->>E: embed_texts
  W->>PG: INSERT chunks (text + embedding + tsv)
  W->>PG: stage = done
```

## Low-level: research (ask → cited answer)

The product path is a single `POST /api/research/chat` that opens a one-way
AG-UI Server-Sent Events stream (TanStack AI `useChat` on the client). Progress
uses the fixed vocabulary in [`docs/ux.md`](docs/ux.md); citations arrive as a
separate `CUSTOM` event and are resolved against `[n]` markers in the answer.

The legacy WebSocket endpoint (`/api/research/ws`) is retained for manual
testing but is no longer the product path.

```mermaid
sequenceDiagram
  participant UI as Web (TanStack useChat)
  participant API as POST /api/research/chat (SSE)
  participant AG as Research Agent
  participant MG as Model Gateway
  participant RET as Retrieval pipeline
  participant PG as PostgreSQL
  participant TV as Vector index

  UI->>API: POST {"question": "...", "threadId": "..."}
  API-->>UI: RUN_STARTED / TEXT_MESSAGE_START
  API->>PG: research_runs (running)
  AG->>MG: ReAct · may call retrieve_evidence
  AG->>RET: retrieve(query, workspace_id)
  RET->>MG: HyDE expand
  RET->>PG: PostgreSQL FTS / workspace allowlist
  RET->>TV: dense ANN
  RET->>RET: RRF + rerank
  RET-->>AG: chunks + source_ref
  Note over AG: citations attached at retrieval time
  loop progress
    API-->>UI: CUSTOM stage (Searching → Reviewing → Generating → Finalizing)
  end
  AG->>MG: draft answer
  AG->>PG: citations + answer
  API-->>UI: CUSTOM citations
  API-->>UI: TEXT_MESSAGE_CONTENT (answer)
  API-->>UI: TEXT_MESSAGE_END / RUN_FINISHED
```

## Data model (conceptual)

```mermaid
erDiagram
  users ||--o{ workspaces : owns
  workspaces ||--o{ documents : contains
  documents ||--|| ingestion_jobs : tracks
  documents ||--o{ chunks : splits_into
  workspaces ||--o{ research_runs : has
  research_runs ||--o{ citations : cites
  citations }o--|| chunks : points_to

  documents {
    uuid id
    string source_type
    string storage_path
  }
  chunks {
    uuid id
    text text
    vector embedding
    string turbovec_id
  }
  research_runs {
    uuid id
    text question
    text answer
    string status
  }
```

Postgres is authoritative for chunk text, metadata, and vectors. `chunks.embedding` (pgvector) is the index — no separate vector store to sync or rebuild (see ADR-002 addendum).

## API surface (MVP)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/ingestion/upload` | Upload file, enqueue job |
| `GET` | `/api/ingestion/jobs/{id}` | Poll ingestion stage |
| `GET` | `/api/ingestion/jobs/failed` | Dead-letter list: failed jobs + errors |
| `POST` | `/api/ingestion/jobs/{id}/retry` | Reset rows + re-enqueue a failed job |
| `GET` | `/api/ingestion/documents` | List documents |
| `DELETE` | `/api/ingestion/documents/{id}` | Delete document + chunks, invalidate caches |
| `POST` | `/api/research/chat` | AG-UI SSE stream: stages → answer → citations (primary) |
| `WS` | `/api/research/ws` | Legacy question → progress → answer (manual testing) |
| `GET` | `/api/research/runs` | List runs (paginated, with token counts) |
| `GET` | `/api/research/runs/{id}` | Fetch a completed run |
| `GET` | `/api/research/usage` | Per-user token spend vs daily budget |
| `GET` | `/api/conversations` | List threads |
| `POST` | `/api/conversations` | Create thread |
| `GET` | `/api/conversations/{id}` | Get thread + runs |
| `POST` | `/api/research/voice` | Voice STT → agent → TTS |
| `GET` | `/healthz` | Liveness |
| `GET` | `/readyz` | Readiness (DB + Redis + Cohere probe) |

## Quick start

```bash
# JS monorepo
pnpm install

# API (from apps/api/)
uv sync
# configure apps/api/.env — DATABASE_URL, REDIS_URL, model keys
uv run alembic upgrade head
uv run python scripts/seed.py
uv run uvicorn app.main:app --reload --port 8000

# Worker (second terminal, apps/api/)
uv run arq app.workers.WorkerSettings

# Web (optional)
pnpm --filter web dev
```

Details: [`apps/api/SETUP.md`](apps/api/SETUP.md), [`docs/AGENTS.md`](docs/AGENTS.md).

## Docs map

| Doc | Role |
| --- | --- |
| [`docs/PRD.md`](docs/PRD.md) | MVP goals and non-goals |
| [`docs/latest-architecture.html`](docs/latest-architecture.html) | Full V1 interactive architecture |
| [`docs/REMAINING.md`](docs/REMAINING.md) | Remaining work checklist |
| [`docs/specs/`](docs/specs/) | Ingestion, retrieval, researcher contracts |
| [`docs/adr/`](docs/adr/) | LangGraph, pgvector, Model Gateway |
| [`ROADMAP.md`](ROADMAP.md) | Get-it-testable steps + future plan |

## Tech stack

- **API:** Python 3.11+, FastAPI, LangGraph, arq, SQLAlchemy async  
- **Retrieval:** Cohere embed-v3, hybrid RRF (dense + PostgreSQL FTS), Cohere rerank-v3, pgvector
- **Models:** Model Gateway (Groq → OpenRouter)  
- **Web:** Next.js 16, React 19, pnpm + Turborepo  
- **Data:** PostgreSQL (Neon), Redis (Upstash / arq)
