# Spec: Composed Research Pipeline (Plan → Research → Synthesize)

## Purpose

Restructure the single-node research loop into a composed LangGraph
pipeline: a cheap-model **planner node** decomposes the question into
1–3 search aspects before the ReAct loop runs, and a dedicated
**synthesize node** owns final-answer generation. Same public contract
(`run_agent` signature, `AgentResult`, wire format, stage vocabulary) —
better decomposition coverage and clearer separation of concerns.

## Justification vs `PRD.md` Non-Goals

The PRD defers the V1 **Planner Agent** ("single-question MVP doesn't
need multi-hop decomposition yet") pending measurement capability. Both
conditions are now resolved:

1. **Nodes, not agents.** This spec adds two LangGraph *nodes* inside
   the existing single research graph (ADR-001 explicitly anticipated
   this: "adding Planner and Critic nodes later is additive"). There is
   no new agent surface, no inter-agent protocol, no plan cache.
2. **Measurement exists.** The offline eval harness
   (`docs/specs/evaluation.md`) provides the baseline the PRD's
   "add once we can measure" condition required. Planner value is
   verified by ΔNDCG/recall movement on multi-aspect golden cases.

`PRD.md` Non-Goals table amended accordingly (mirrors the ADR-007
semantic-cache precedent).

## Dependencies

`src/research/agent.py`, `src/shared/model_gateway.py` (`complete`,
`complete_with_tools` — all inference stays behind the gateway,
ADR-003), LangGraph StateGraph (ADR-001), `docs/specs/researcher.md`.

## Graph Contract

```
entry → planner → researcher ⇄ (loop, ≤ MAX_ITERATIONS)
                       ↓ (answer written OR iterations exhausted)
                  synthesize → END
```

### Planner node
- Input: `question`. Output: `plan: list[str]` (1–3 search queries) plus
  a system message injecting the plan into the conversation.
- Cheap-model call, temperature 0, ≤ 200 tokens, JSON array output.
- Parse-tolerant: accepts plain or code-fenced arrays; caps at 3;
  drops empty/non-string entries.
- **Never fails the run:** provider errors, timeouts, or unparseable
  output fall back to `[question]` (single-step plan).
- Emits **no** progress stage — the fixed `ux.md` vocabulary is
  untouched; `SEARCHING` still fires on first retrieval.

### Researcher node
Unchanged ReAct loop (see `docs/specs/researcher.md`). The forced
best-effort completion moves out of this node into synthesize.

### Synthesize node
- Pass-through when the researcher already wrote `answer`.
- Otherwise (iteration cap hit): one grounded generation call without
  tools using the exact prompt the inline path used before — identical
  behavior, owned by one node.

## Invariants

- `run_agent()` signature, `AgentResult` fields, citation persistence,
  confidence assessment, hard refusal: unchanged.
- Citations survive exactly as before (citation-at-retrieval contract).
- Stage vocabulary: `SEARCHING → REVIEWING → GENERATING → FINALIZING`.
- Checkpointing: `thread_id` is fresh per run, so the added `plan`
  state key introduces no cross-version replay risk.

## Success Criteria

- Planner decomposes multi-aspect questions; falls back cleanly on any
  failure (unit-tested).
- Synthesize handles both pass-through and forced-generation paths.
- Full-graph smoke test runs offline (gateway mocked) and produces a
  cited answer through plan → research → synthesize.
- Existing `run_agent` tests stay green without modification.

## Out of Scope (Deferred)

Critic/verifier node and reflection loop (needs its own spec + baseline
failure data), plan cache (nothing to reuse until plans repeat),
multi-agent trajectory UI.
