# ADR-0004: PostgreSQL + ClickHouse + pgvector
Status: Accepted · Date: 2026-11-13

## Context
Three access patterns: transactional state with relations and constraints; high-volume append-only time series with aggregations; semantic and keyword retrieval over documents.

## Decision
- PostgreSQL: tenants, devices, credentials, latest state, commands, incidents, audit, outbox.
- ClickHouse: raw telemetry and rollups (MergeTree family).
- pgvector in PostgreSQL for embeddings, with `tsvector` for hybrid search.
- Start with PostgreSQL only in slice S1; add ClickHouse in S2 so the comparison against a Postgres-only baseline is real and measured.

## Alternatives considered
- PostgreSQL/TimescaleDB only: simpler, but loses the demonstration of a purpose-built analytics store.
- Dedicated vector database: extra system for a small corpus; pgvector suffices.

## Consequences
+ Right tool per workload; benchmarks can compare strategies.
− Two stores to keep consistent; ClickHouse deduplication is eventual.
Mitigation: ingestion is idempotent; latest state lives in PostgreSQL; ClickHouse is never the source for control decisions.

## Revisit when
Benchmarks show the dual-store complexity is not justified at the demonstrated scale (document the finding either way).
