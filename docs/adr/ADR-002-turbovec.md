# ADR-002: Turbovec for Vector Retrieval

**Status:** Accepted
**Date:** 2026-06-22
**Deciders:** Project architecture (frozen V1 design)

## Context
The MVP needs dense vector retrieval over document chunks, fused with
keyword (BM25) search, with metadata pre-filtering so retrieval can be
scoped (by workspace, document, etc.) without scanning every vector.

## Decision
Use Turbovec as the vector index. PostgreSQL sits in front of it: Postgres
holds chunk metadata and runs the pre-filter that produces an ID allowlist,
which Turbovec's SIMD-accelerated scoring kernel applies during the search
itself — not as a separate post-filter step.

## Options Considered

### Option A: pgvector (in-Postgres vector extension)
| Dimension | Assessment |
|---|---|
| Complexity | Low — one database, no second system |
| Cost | None beyond existing Postgres |
| Scalability | Adequate at small-to-medium scale; full-precision vectors cost more memory per vector than a quantized index |
| Team familiarity | High — it's still just Postgres |

**Pros:** Single system, simplest possible ops story.
**Cons:** No built-in 4-bit-style compression; memory cost per vector is
materially higher at scale than a purpose-built ANN index.

### Option B: Qdrant (managed/self-hosted vector DB)
| Dimension | Assessment |
|---|---|
| Complexity | Medium — a second service to run and operate |
| Cost | Self-hosting cost, or managed-tier cost |
| Scalability | Strong; native filtering and a dashboard |
| Team familiarity | Medium |

**Pros:** Full-featured vector database with its own metadata filtering and
operational tooling.
**Cons:** A whole second database to run for a single-tenant MVP that
already has Postgres for everything else.

### Option C: Turbovec
| Dimension | Assessment |
|---|---|
| Complexity | Low-Medium — it's a library, not a service, but needs Postgres in front of it for metadata/filtering since it has none natively |
| Cost | None (open source); ~4GB for 10M vectors via 4-bit quantization vs. ~31GB unquantized |
| Scalability | High vectors-per-GB efficiency; SIMD-accelerated; filters inside the scoring loop via ID allowlists |
| Team familiarity | Low — newest tool in the stack |

**Pros:** Smallest memory footprint by far, and filtering happens *inside*
the scoring kernel rather than as a slower post-filter pass.
**Cons:** It's a library with no dashboard and no native metadata
filtering — Postgres has to do that job, which is an extra moving part
compared to Option B.

## Trade-off Analysis
pgvector is the lowest-complexity option but trades away the
compression/efficiency Turbovec offers at scale. Qdrant offers the most
built-in tooling but adds a second stateful service the MVP doesn't need.
Turbovec's efficiency and SIMD-level filtering match the architecture's
"Postgres is metadata source of truth, Turbovec is a pure vector index"
split — the extra wiring (Postgres prefilter → Turbovec allowlist) is a
one-time integration cost paid once, not an ongoing operational one.

## Consequences
- Easier: very low memory cost per vector even as the document set grows
- Easier: filtering is fast because it happens inside the kernel
- Harder: no dashboard or admin UI — observability comes from Langfuse/logs
- Harder: Turbovec has zero value without Postgres in front of it; the two
  must be kept in sync (see `schema.md` — Postgres is authoritative)

## Action Items
1. [ ] Implement the Postgres metadata pre-filter that produces the ID
   allowlist consumed by Turbovec (see `docs/specs/retrieval.md`)
2. [ ] Ensure every `chunks` row has a corresponding Turbovec vector and vice
   versa — no orphaned vectors
