# ADR-0002: Rust for the device plane, Python for the agent plane
Status: Accepted · Date: 2026-11-13

## Context
The device plane needs predictable latency, bounded memory, high concurrency and strong typing for safety rules. The agent plane needs the LLM ecosystem (LangGraph, embeddings, evaluation tools).

## Decision
Rust (Tokio, Axum, SQLx) owns ingestion, APIs, commands, policy and rules. Python (FastAPI, LangGraph) owns reasoning, RAG and evals. They communicate only over HTTP with scoped tokens; Python has no database access to Rust-owned tables.

## Alternatives considered
- All Python: faster agent iteration, weaker guarantees for the ingest hot path.
- All Rust: ecosystem gaps for LangGraph/RAG evaluation.
- TypeScript backend: unifies web and backend, but weaker fit for the systems goals of the project.

## Consequences
+ Safety decisions stay in typed, testable Rust; agent code cannot bypass them.
+ Clear failure isolation: agent down does not stop operations.
− Two toolchains and an API boundary to maintain.
Mitigation: OpenAPI and JSON Schema generated from Rust types, consumed by Python and TypeScript.

## Revisit when
The API boundary becomes a measured bottleneck for agent tool latency.
