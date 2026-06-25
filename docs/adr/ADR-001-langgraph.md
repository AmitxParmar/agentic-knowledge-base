# ADR-001: LangGraph for Agent Orchestration

**Status:** Accepted
**Date:** 2026-06-22
**Deciders:** Project architecture (frozen V1 design)

## Context
The MVP runs a single Research Agent. The V1 architecture, however, models
the eventual system as Planner → Researcher → Critic: a cyclic graph with a
reflection loop (Critic sends work back to the Researcher) and checkpointed
state. Whatever orchestration layer the MVP picks needs to absorb that shape
later without a rewrite.

## Decision
Use LangGraph to orchestrate the Research Agent, even though MVP has only
one node. The graph is built so adding Planner and Critic nodes later is an
additive change, not a restructure.

## Options Considered

### Option A: Plain function-calling loop (hand-rolled ReAct)
| Dimension | Assessment |
|---|---|
| Complexity | Low for one agent |
| Cost | None (no extra dependency) |
| Scalability | Breaks down once a reflection loop or multi-agent handoff is needed |
| Team familiarity | High — it's just a while-loop |

**Pros:** Simplest possible MVP, zero new dependency.
**Cons:** No built-in state checkpointing; adding a cycle (Critic → back to
Researcher) later means re-architecting the control flow, not extending it.

### Option B: Custom state machine
| Dimension | Assessment |
|---|---|
| Complexity | Medium — building and testing the state machine itself |
| Cost | None |
| Scalability | Works, but checkpoint/recovery logic is hand-built |
| Team familiarity | Medium |

**Pros:** Full control, no framework lock-in.
**Cons:** Reinvents exactly what LangGraph already provides — cyclic graphs
with per-step checkpointing — for no benefit at this scale.

### Option C: LangGraph
| Dimension | Assessment |
|---|---|
| Complexity | Low–Medium (one new dependency, well-documented for this exact shape) |
| Cost | None (open source) |
| Scalability | Native support for cycles and per-step checkpoint/recovery — exactly what Planner→Researcher→Critic→Researcher needs later |
| Team familiarity | Learning curve for the graph abstraction itself |

**Pros:** The checkpoint-recovery and cyclic-graph pattern the V1 design
needs is already solved. A single-node graph today is structurally identical
to a three-node graph later.
**Cons:** Pulls in a framework for what is currently one node — slight
overhead today in exchange for not rewriting the orchestration layer later.

## Trade-off Analysis
The real choice is "pay a small framework cost now" vs. "pay a rewrite cost
when the Critic reflection loop is added." Since the reflection loop and
checkpointing are explicit, already-designed parts of the frozen V1
architecture (not speculative), the framework cost is justified now.

## Consequences
- Easier: adding Planner and Critic nodes later is additive
- Easier: state checkpointing/recovery for long-running research runs
- Harder: one more dependency and abstraction to learn for a single-node MVP
- Revisit: if LangGraph's overhead proves unjustified before Planner/Critic
  are actually built, this ADR should be revisited — but not before then

## Action Items
1. [ ] Define the MVP graph as a single Research Agent node with a bounded
   ReAct loop inside it (see `docs/specs/researcher.md`)
2. [ ] Confirm checkpointing is configured even for the single-node graph,
   so recovery behavior is tested before Planner/Critic exist
