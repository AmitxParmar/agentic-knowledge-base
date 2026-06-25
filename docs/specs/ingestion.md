# Spec: Ingestion Pipeline

## Purpose
Turn an uploaded PDF, code repository, or audio file into searchable,
citable chunks.

## Dependencies
ADR-002 (Turbovec), `schema.md` (`documents`, `ingestion_jobs`, `chunks`),
`docs/ui/ux.md` (progress-stage wording emitted at each step below).

## Scope
Upload through "searchable." Does not cover how chunks are queried — see
`docs/specs/retrieval.md` for that.

## Pipeline Stages

| Stage | Input | Output | Tool |
|---|---|---|---|
| 1. Upload | Raw file | `documents` row + `ingestion_jobs` row (queued); raw file written to disk | FastAPI → async worker |
| 2. Extract | Raw file, by type | Structured text (headings/tables preserved for PDF; transcript for audio; AST-bounded units for code) | Docling (PDF) · faster-whisper (audio) · tree-sitter + gitingest (repo) |
| 3. Chunk | Extracted structured text | Semantically-bounded chunks (boundaries follow meaning shifts, not fixed token counts) | Chonkie |
| 4. Extract metadata | Chunks + document | Author/date/category tags inherited from document-level extraction down to each chunk | Metadata extraction step |
| 5. Embed | Chunk text | Vector per chunk | BGE-M3 (self-hosted, separate from the chat model) |
| 6. Persist | Vectors + chunk text/metadata | Vectors written to Turbovec; chunk rows + metadata written to Postgres | — |

The document is marked searchable only after stage 6 completes for every
chunk.

## Per-Source-Type Notes
- **PDF:** Docling preserves heading hierarchy, tables, and lists as
  structured objects, not flattened text — this is what lets chunking
  respect document structure instead of cutting mid-paragraph.
- **Audio:** faster-whisper transcribes before chunking; the transcript is
  treated like any other extracted text from that point on.
- **Code repo:** tree-sitter parses each file into an AST so chunk
  boundaries land on function/class boundaries — a chunk cut mid-function is
  treated as worse than no chunk.

## Success Criteria
- A document becomes searchable (queryable via `docs/specs/retrieval.md`)
  without manual steps after upload.
- Every chunk has both a Postgres row and a Turbovec vector — no orphans in
  either direction (see `schema.md`).
- Progress events fire at each stage transition, using the exact wording in
  `docs/ui/ux.md` (e.g., "Extracting content...", "Creating embeddings...").
- A failed stage marks the `ingestion_jobs` row failed with an error detail,
  rather than leaving it stuck in an intermediate state.

## Out of Scope (MVP)
Incremental re-ingestion on document update, and any ingestion triggered by
something other than a direct user upload (e.g., scheduled re-crawl).
