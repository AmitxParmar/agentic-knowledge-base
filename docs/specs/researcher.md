# Spec: Research Agent

## Purpose
The MVP's only agent. Takes a user's question, retrieves evidence from the
user's uploaded documents, and produces a citation-backed answer.

## Dependencies
`docs/specs/retrieval.md` (its only tool), ADR-001 (LangGraph), ADR-003
(Model Gateway), `schema.md` (`research_runs`, `citations`).

## Scope
This agent only. Planner and Critic are separate future specs — see
`PRD.md` → Non-Goals for why they aren't here yet.

## Inputs
| Input | Description |
|---|---|
| `question` | The user's natural-language question |
| `workspace_id` | Scopes which documents/chunks are eligible for retrieval |
| (implicit) retrieved evidence | Pulled via the retrieval tool during the loop, not passed in upfront |

## Outputs
| Output | Description |
|---|---|
| `answer` | The drafted response text |
| `citations` | List of chunk references supporting specific claims in the answer |
| progress events | Named stage events emitted during the run (see `docs/ui/ux.md`) |

## Tools (MVP)
| Tool | Purpose |
|---|---|
| Hybrid retrieval | The only tool. Calls the pipeline in `docs/specs/retrieval.md` (rewrite → hybrid search → rerank) and returns ranked chunks with scores and source references |

No other tools exist for MVP. Web search, GitHub, and filesystem tools (MCP
Tool Layer in the V1 design) are Phase 2 — see `PRD.md`.

## Behavior — Loop Pattern
ReAct: Reason → Act (call retrieval) → Observe, repeated until the agent has
enough evidence to answer or hits the iteration bound below.

- A citation is attached to a piece of evidence **at the moment it's
  retrieved** — never reconstructed by scanning the final answer text
  afterward (see `conventions.md` → Citation-at-retrieval pattern).
- All model calls (reasoning, drafting) go through the Model Gateway —
  never a direct provider call (ADR-003).

## Constraints
- **Iteration bound:** a fixed maximum number of retrieval calls per run.
  This is a minimal stand-in for the V1 design's full Circuit Breaker (which
  also bounds reflection passes and total cost) — those don't apply yet
  since there's no Critic and no reflection loop to bound.
- No multi-agent handoff: this agent runs start to finish alone.

## Success Criteria
- Every factual claim in the answer is traceable to at least one cited
  chunk.
- The answer addresses the question asked (not a tangential restatement of
  retrieved content).
- The run completes within the iteration bound — if evidence is
  insufficient, the agent says so rather than fabricating an answer.
- Every run is fully traced in Langfuse (inputs, tool calls, outputs).

## Out of Scope (MVP)
Task decomposition into sub-tasks (Planner), draft review/reflection
(Critic), plan reuse (Plan Cache), and any persistent memory across runs.
