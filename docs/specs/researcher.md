# Spec: Research Agent

## Purpose
The MVP's only agent. Takes a user's question, retrieves evidence from the
user's uploaded documents, and produces a citation-backed answer.

## Dependencies
`docs/specs/retrieval.md` (its only tool), ADR-001 (LangGraph), ADR-003
(Model Gateway), `schema.md` (`research_runs`, `citations`).

## Scope
This agent only. Pipeline composition (planner/synthesize nodes) lives in
`docs/specs/research-pipeline.md`; a Critic remains a future spec - see
`PRD.md` Non-Goals for why they aren't here yet.

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
| `confidence` | `"sufficient"` or `"insufficient"` — whether the agent found adequate evidence |
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

### Iteration / Cost Bound
- **`MAX_ITERATIONS`** (hard-coded 5): maximum retrieval calls per run.
  When reached, the agent drafts its best answer from evidence gathered so
  far and terminates — it does not continue searching.
- Minimal stand-in for the V1 Circuit Breaker; no Critic or reflection loop
  to bound yet.

### Timeouts (Step 6 hardening)
| Scope | Setting | Default |
|---|---|---|
| Overall agent run | `AGENT_RUN_TIMEOUT` | 60 s |
| Per-iteration LLM call | `AGENT_ITERATION_TIMEOUT` | 30 s |

`graph.ainvoke()` is wrapped in `asyncio.wait_for(AGENT_RUN_TIMEOUT)`.
Each `complete_with_tools()` call is wrapped in
`asyncio.wait_for(AGENT_ITERATION_TIMEOUT)`. On `asyncio.TimeoutError`
the run is marked `failed` and a `RUN_ERROR` SSE event is emitted to
the client.

### Evidence Assessment
After the loop, the agent evaluates whether retrieved evidence is
sufficient to support a factual answer:
- `confidence: "sufficient"` — citations were found and relevance scores
  meet a minimum threshold.
- `confidence: "insufficient"` — no citations or all relevance scores fall
  below threshold. The agent explicitly tells the user evidence was thin
  rather than fabricating an answer.

The `confidence` field is stored on `research_runs` and surfaced to the
frontend in the SSE event stream so the UI can display a warning banner
when evidence was thin.

- No multi-agent handoff: this agent runs start to finish alone.

## Success Criteria
- Every factual claim in the answer is traceable to at least one cited
  chunk.
- The answer addresses the question asked (not a tangential restatement of
  retrieved content).
- The run completes within `AGENT_RUN_TIMEOUT` (60 s) or terminates
  cleanly with a `RUN_ERROR` event — it never hangs indefinitely.
- When evidence is insufficient, `confidence` is `"insufficient"` and the
  agent states this explicitly — it does not fabricate citations.
- Every run is fully traced in Langfuse (inputs, tool calls, outputs).

## Out of Scope (MVP)
Task decomposition into sub-tasks (Planner), draft review/reflection
(Critic), plan reuse (Plan Cache), and any persistent memory across runs.
