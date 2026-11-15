# ADR-0011: One investigation agent on LangGraph
Status: Accepted · Date: 2026-11-13

## Context
Agent value comes from reasoning over evidence and choosing among tools. Multi-agent designs add coordination failure modes and cost before a single agent is reliable.

## Decision
Build one stateful investigation graph (gather evidence → retrieve docs → hypothesize → diagnose → propose → await approval → verify) with a PostgreSQL checkpointer, explicit budgets, scoped tools, and Langfuse tracing. Evaluate it with at least 50 scenarios before considering delegation.

## Alternatives considered
- Plain function pipeline with no graph: simpler, but weaker for loops, resumability and approval waits.
- Multi-agent crew: more moving parts, harder to evaluate and secure.

## Consequences
+ Resumable, inspectable, measurable runs.
− LangGraph learning curve and version coupling.
Mitigation: keep node logic as plain functions so the graph can be swapped.

## Revisit when
Evaluation shows a clear task class that a specialized second agent improves measurably.
