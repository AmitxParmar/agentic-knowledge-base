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
| 5. Embed | Chunk text | Vector per chunk | Cohere embed-v3 (1024 dims) |
| 6. Persist | Vectors + chunk text/metadata | Vectors written to pgvector; chunk rows + metadata written to Postgres | — |

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

## Hardening Features (Production-Ready)

### Upload Validation (Server-Side)
- **MIME type**: Must be `application/pdf`
- **File size**: Maximum 100 MB
- **PDF header**: Must start with `%PDF-` magic bytes
- **Page count**: Maximum 100 pages
- **Encryption**: Password-protected PDFs rejected
- **Empty/malformed**: Empty or corrupt PDFs rejected

All validation errors return generic user-facing messages (no stack traces).

### Timeouts (Configurable via Settings)
| Operation | Default Timeout |
|---|---|
| PDF parsing | 10 seconds |
| Embedding request | 20 seconds |
| Model gateway call | 30 seconds |

Timeouts return user-friendly "request timed out" errors.

### Retries with Exponential Backoff
- **Max attempts**: 3 (configurable)
- **Base delay**: 0.5s, exponential backoff with jitter
- **Max delay**: 4.0s
- **Retryable**: 429 rate limits, 5xx errors, network timeouts
- **Non-retryable**: Invalid PDF, authentication errors, malformed requests

### Rate Limiting (Per-IP)
| Endpoint | Limit |
|---|---|
| Upload | 5 requests/minute |
| Chat | 20 requests/minute |

Returns HTTP 429 with `Retry-After` header.

### Concurrency Controls
| Resource | Limit |
|---|---|
| Concurrent indexing jobs per user | 2 |
| Concurrent PDF parses | 2 |
| Embedding batch size | 64 (Cohere limit: 96) |

### Storage Safety
- Files stored in private bucket (Backblaze B2 / R2)
- UUID filenames generated; original filename stored only for display
- Filenames sanitized for display

### Parsing Safety
- 10-second PDF parse timeout (via `asyncio.wait_for`)
- Encrypted/password-protected PDFs rejected
- No JavaScript execution (pypdf extracts text only)
- Parser runs in thread pool to avoid blocking event loop

### Observability
Structured Logfire events emitted:
- `upload_started`, `upload_rejected` (with reason)
- `parse_failed`, `embedding_failed`, `embedding_fallback`
- `indexing_completed`, `indexing_failed`
- `retrieval_empty`, `retrieval_low_confidence`
- `rate_limited` (with client IP and endpoint)
- All events include: `request_id`, `workspace_id`, `duration_ms`, token counts

## Success Criteria
- A document becomes searchable (queryable via `docs/specs/retrieval.md`)
  without manual steps after upload.
- Every chunk has both a Postgres row and a pgvector vector — no orphans in
  either direction (see `schema.md`).
- Progress events fire at each stage transition, using the exact wording in
  `docs/ui/ux.md` (e.g., "Extracting content...", "Creating embeddings...").
- A failed stage marks the `ingestion_jobs` row failed with an error detail,
  rather than leaving it stuck in an intermediate state.

## Out of Scope (MVP)
Incremental re-ingestion on document update, and any ingestion triggered by
something other than a direct user upload (e.g., scheduled re-crawl).
