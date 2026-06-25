# UX: Progress Visibility & Citation Display

## Purpose
Define what the user sees while the system works, and draw a hard line
around what they must never see.

## Dependencies
`docs/specs/ingestion.md`, `docs/specs/retrieval.md`,
`docs/specs/researcher.md` — this doc maps their internal stages to the
words shown on screen.

## Scope
Client-facing behavior only. No transport implementation details — just the
contract (what events exist, what they mean, when they fire).

## Core Principle
**Never expose chain-of-thought, internal reasoning, or hidden prompts.**
The user sees *what* the system is doing, never *how* the model is thinking.
Progress stages are the only window into an in-progress run.

## MVP User Flow
1. Upload a document (PDF, repo, or audio).
2. Ask a question.
3. Receive an answer with citations back to source chunks.
4. Watch progress stages throughout steps 1 and 3 — never a bare spinner,
   never raw model output mid-run.

## Progress Stage Vocabulary

### Ingestion (maps to `docs/specs/ingestion.md` stages 1–6)
| Stage shown to user | Pipeline step |
|---|---|
| Uploading document... | Stage 1 |
| Extracting content... | Stage 2 |
| Chunking content... | Stage 3 |
| Creating embeddings... | Stages 4–5 |

### Research Run (maps to `docs/specs/researcher.md` / `retrieval.md`)
| Stage shown to user | Pipeline step |
|---|---|
| Searching documents... | Hybrid retrieval call |
| Reviewing evidence... | Agent evaluating retrieved chunks |
| Generating report... | Drafting the answer |
| Finalizing answer... | Attaching citations, returning the response |

These exact strings are the only vocabulary allowed on the progress
channel — see `conventions.md` → Progress-event pattern. Don't invent new
stage text ad hoc; add a row here first if a new stage is genuinely needed.

## Citation Display Requirement
Every claim in the final answer that's backed by retrieved evidence must
show a visible link to its source chunk/document (e.g., a numbered
reference the user can click to see the source passage). An answer with no
visible citations has failed `docs/specs/researcher.md` → Success Criteria,
regardless of how the text reads.

## Explicitly Forbidden on the Client
- Raw chain-of-thought or scratchpad reasoning
- Hidden system/agent prompts
- Internal tool-call payloads (the retrieval query, rerank scores, etc.) —
  only the *stage name*, never the *call contents*

## Out of Scope (MVP)
Live-streamed Planner/Critic trajectory views (the V1 design's "watch the
reasoning unfold" chat UI) — that's a Phase 2 feature once those agents
exist. MVP shows stage names only, not a multi-agent trace view.
