# schema.md

## Purpose
A conceptual data model for the MVP — entities, relationships, and ownership
boundaries. Detailed enough for a coding agent to generate SQLAlchemy models
and Alembic migrations from, without prescribing the SQL itself.

## Dependencies
`docs/architecture.html` (PostgreSQL is the system's relational source of
truth), `PRD.md` (scopes which entities are needed now vs. Phase 2).

## Scope
Conceptual schema only — entities, attributes (by meaning, not SQL type),
relationships, ownership. No DDL, no ORM code, no index definitions.

## Architecture Principle This Schema Follows
Per `docs/architecture.html`: PostgreSQL holds all metadata, relationships,
and full chunk text — it is the durable source of truth. Turbovec holds only
the vector index, keyed by `chunk_id`, with no metadata of its own. Every
embedding row in Turbovec must correspond to exactly one `chunks` row in
Postgres; Turbovec is rebuildable from Postgres, never the other way around.

## Core Entities

### `users`
A person using the workspace.
- Identity attributes (name, email, auth identifier)
- One user can belong to one or more workspaces

### `workspaces`
A container that scopes documents and research runs. Even though MVP is
single-tenant in practice, the entity exists now so multi-tenancy isn't a
schema rewrite later.
- Owner reference → `users`
- Created/updated timestamps

### `documents`
A single uploaded source (one PDF, one repo, one audio file).
- Belongs to exactly one `workspace`
- Source type (pdf / repo / audio)
- Original filename / source reference (e.g., git URL)
- Pointer to the raw file in storage (filesystem path)
- Processing status (mirrors the related `ingestion_jobs` row)

### `ingestion_jobs`
Tracks the async pipeline run for one document, from upload to searchable.
- Belongs to exactly one `document`
- Stage (queued / extracting / chunking / embedding / done / failed)
- Error detail, if failed
- Timestamps per stage transition

### `chunks`
A semantically-bounded piece of a document's content — the unit that gets
embedded, retrieved, and cited.
- Belongs to exactly one `document`
- Ordinal position within the document
- Full chunk text (so Postgres alone can answer "what does this chunk say")
- Reference to its vector in Turbovec (the `chunk_id` is the join key)
- Metadata (author/date/category, inherited from document-level extraction)

### `research_runs`
One question-asking session: a user's question through to the final answer.
- Belongs to exactly one `workspace`; initiated by one `user`
- The question text
- The final answer text
- Status (running / complete / failed)
- Timestamps

### `citations`
The traceability link between a claim in a `research_run`'s answer and the
evidence that supports it.
- Belongs to exactly one `research_run`
- References exactly one `chunk`
- Optionally: the span of the answer text the citation supports

## Relationships

| From | To | Cardinality | Meaning |
|---|---|---|---|
| `users` | `workspaces` | 1 → many | A user can own/access multiple workspaces |
| `workspaces` | `documents` | 1 → many | A workspace contains many documents |
| `documents` | `ingestion_jobs` | 1 → 1 (current) | One active job tracks one document's processing |
| `documents` | `chunks` | 1 → many | A document is split into many chunks |
| `workspaces` | `research_runs` | 1 → many | A workspace has a history of research runs |
| `research_runs` | `citations` | 1 → many | One answer can cite many chunks |
| `citations` | `chunks` | many → 1 | Many citations across many runs can point at the same chunk |

## Ownership Boundaries
- A `workspace` is the scoping boundary for everything below it —
  `documents`, `chunks` (via `documents`), and `research_runs` all belong to
  exactly one workspace and should never be queried across workspaces.
- A `chunk`'s vector lives in Turbovec; its text and metadata live in
  Postgres. Postgres is authoritative — if the two disagree, Postgres wins
  and Turbovec is re-indexed from it.

## Data Flow Summary
```
Upload → document row created → ingestion_job created (queued)
       → extraction/chunking/embedding stages update the job
       → chunks rows written (text + metadata) + vectors written to Turbovec
       → document marked searchable

Question → research_run row created
        → Research Agent retrieves chunks (Turbovec + Postgres hybrid search)
        → answer drafted with citations rows linking run → chunks
        → research_run marked complete
```

## Deferred Entities (Phase 2 — Do Not Build Yet)
`plan_cache`, `semantic_memory`, `conversation_summaries` — these belong to
the Planner/Critic/memory layers explicitly out of scope per `PRD.md`.
