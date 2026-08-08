# Spec: Conversation History

## Purpose
Persist conversation threads server-side so research history survives a page
reload. A thread is an ordered sequence of research runs; each run's
question, answer, and citations already live in `research_runs`/`citations`.
This spec adds the thread container that groups runs and stores the user-visible
title.

## Dependencies
`docs/specs/researcher.md` (defines `research_runs` and `citations`),
`docs/schema.md` (data model — adds `conversation_threads`), ADR-001 (FastAPI),
`schema.md` (`workspaces` FK scope).

## Scope
Thread lifecycle only: create, list (by workspace), rename, delete, and
append a run to a thread. Message-level storage is out of scope — the actual
Q&A content is already persisted per-`research_run`. This spec does NOT add
`conversation_summaries`, `plan_cache`, or `semantic_memory` (those stay
Phase 2 per `schema.md`).

## Model — `conversation_threads`
| Attribute | Meaning |
|---|---|
| `id` | UUID primary key |
| `workspace_id` | Scoping boundary → `workspaces.id` |
| `title` | User-visible label (defaults to first question) |
| `created_at` | Creation timestamp |
| `updated_at` | Last activity timestamp |

A thread's runs are the `research_runs` rows ordered by `created_at`. We do
not add a `thread_id` FK to `research_runs` in MVP — thread membership is
derived client-side from the ordered list of run ids the thread stores. This
keeps the existing research-run write path (the agent) untouched.

## API
All endpoints are scoped to the caller's workspace (via `get_workspace_id`).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/conversations` | List threads for the workspace, newest first |
| `POST` | `/api/conversations` | Create a new thread (optionally seeded with a run id) |
| `GET` | `/api/conversations/{id}` | Get one thread + its runs (question/answer/citations) |
| `PATCH` | `/api/conversations/{id}` | Rename a thread |
| `DELETE` | `/api/conversations/{id}` | Delete a thread |

### `GET /api/conversations` response
```json
{
  "threads": [
    {
      "id": "uuid",
      "title": "...",
      "run_count": 3,
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

### `GET /api/conversations/{id}` response
```json
{
  "thread": { "id": "...", "title": "...", "created_at": "...", "updated_at": "..." },
  "runs": [
    {
      "id": "...",
      "question": "...",
      "answer": "...",
      "status": "complete",
      "citations": [{"chunk_id": "...", "source_ref": "...", "relevance_score": 0.91}],
      "created_at": "..."
    }
  ]
}
```

## Client contract
`useConversations` keeps its in-memory API (`threads`, `ensureThread`,
`removeThread`, `startNew`, `syncMessages`) but swaps persistence: thread
metadata (id/title) is server-backed, while the live message list is still held
in memory keyed by threadId. On mount, the client `GET`s threads; creating or
renaming a thread `POST`s/`PATCH`es. This matches the "prep for server
persistence" seam already built into the store.

## Out of scope (MVP)
- Editing/deleting individual messages
- Message-level persistence (the `research_runs` row already persists the
  question + answer; chat *transcript* persistence is Phase 2)
- Sharing threads across workspaces
- Search within a thread
