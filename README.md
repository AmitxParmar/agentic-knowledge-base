# Agentic Research Workspace

Enterprise **agentic RAG knowledge base**: upload your documents, ask questions, get **citation-backed** answers.

MVP scope is a single **Research Agent** (ReAct) over hybrid retrieval. The frozen V1 design also includes Planner, Critic, semantic cache, and MCP tools — see [`docs/PRD.md`](docs/PRD.md) and [`docs/latest-architecture.html`](docs/latest-architecture.html).

| Layer | What it does |
| --- | --- |
| **Knowledge base** | PDF / repo / audio → extract → chunk → embed → Postgres + vectors |
| **RAG** | HyDE → dense + BM25 hybrid (RRF) → rerank → cite chunks |
| **Agentic** | LangGraph Research Agent: reason → retrieve → draft under an iteration cap |

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
    WS["WebSocket<br/>/api/research/ws"]
  end

  subgraph Ingest["Ingestion · arq workers"]
    Q["Redis queue"]
    X["Extract<br/>Docling · whisper · tree-sitter"]
    C["Chunk · Chonkie"]
    E["Embed · BGE-M3"]
  end

  subgraph Retrieval["Retrieval engine"]
    HYDE["Query rewrite · HyDE"]
    HYB["Hybrid search + RRF"]
    RER["Rerank · BGE"]
  end

  subgraph Agent["Orchestration · LangGraph"]
    RA["Research Agent · ReAct"]
  end

  subgraph Storage
    PG[("PostgreSQL<br/>metadata · chunks · FTS")]
    TV[("Turbovec / vectors<br/>rebuildable from PG")]
    FS[("File storage<br/>raw uploads")]
  end

  subgraph Models["Model Gateway · ADR-003"]
    MG["complete / complete_with_tools<br/>Groq → OpenRouter"]
  end

  WEB --> REST & WS
  CLI --> REST & WS
  REST --> Q --> X --> C --> E
  REST --> FS
  E --> PG & TV
  WS --> RA
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
  W->>PG: INSERT chunks
  W->>TV: upsert by chunk_id
  W->>PG: stage = done
```

## Low-level: research (ask → cited answer)

One WebSocket connection per run. Progress uses the fixed vocabulary in [`docs/ux.md`](docs/ux.md). Answer is currently sent as a full blob (token streaming not implemented yet).

```mermaid
sequenceDiagram
  participant UI as Web / wscat
  participant API as research WS
  participant AG as Research Agent
  participant MG as Model Gateway
  participant RET as Retrieval pipeline
  participant PG as PostgreSQL
  participant TV as Vector index

  UI->>API: connect + {"question": "..."}
  API->>PG: research_runs (running)
  API-->>UI: progress Searching documents...
  AG->>MG: ReAct · may call retrieve_evidence
  AG->>RET: retrieve(query, workspace_id)
  RET->>MG: HyDE expand
  RET->>PG: BM25 / workspace allowlist
  RET->>TV: dense ANN
  RET->>RET: RRF + rerank
  RET-->>AG: chunks + source_ref
  Note over AG: citations attached at retrieval time
  API-->>UI: progress Reviewing / Generating / Finalizing
  AG->>MG: draft answer
  AG->>PG: citations + answer
  API-->>UI: answer + citations
  API-->>UI: done
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
    string turbovec_id
  }
  research_runs {
    uuid id
    text question
    text answer
    string status
  }
```

Postgres is authoritative for chunk text and metadata. The vector index is keyed by `chunk_id` and can be rebuilt from Postgres (see ADR-002).

## API surface (MVP)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/ingestion/upload` | Upload file, enqueue job |
| `GET` | `/api/ingestion/jobs/{id}` | Poll ingestion stage |
| `WS` | `/api/research/ws` | Question → progress → answer + citations |
| `GET` | `/api/research/runs/{id}` | Fetch a completed run |
| `GET` | `/health` | Liveness |

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
| [`docs/adr/`](docs/adr/) | LangGraph, Turbovec, Model Gateway |
| [`ROADMAP.md`](ROADMAP.md) | Get-it-testable steps + future plan |

## Tech stack

- **API:** Python 3.11+, FastAPI, LangGraph, arq, SQLAlchemy async  
- **Retrieval:** BGE-M3, hybrid RRF, BGE-Reranker, Turbovec (numpy fallback in dev)  
- **Models:** Model Gateway (Groq → OpenRouter)  
- **Web:** Next.js 16, React 19, pnpm + Turborepo  
- **Data:** PostgreSQL (Neon), Redis (Upstash / arq)
