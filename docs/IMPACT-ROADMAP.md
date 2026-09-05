# Impact Roadmap: Performance, Cost, Quality, and Agentic Evolution

> A prioritised set of improvements for the Agentic Research Workspace. The
> focus is measurable user and business impact—not adding agents for their own
> sake.
>
> Last updated: 2026-08-29

## What “impactful” means

Every proposed change should improve at least one measurable outcome:

| Outcome | Example measures |
| --- | --- |
| Cost | tokens per run, model cost per answer, cache-hit rate |
| Speed | p50/p95 end-to-end latency, retrieval latency, time to first token |
| Quality | retrieval recall@n, nDCG, citation coverage/correctness, grounded-answer rate |
| Reliability | provider failure rate, timeout rate, ingestion success, retry rate |
| User value | time to a trusted answer, successful multi-turn task completion |

Baseline these before and after each change. An improvement that cannot be
measured should remain an experiment rather than become permanent complexity.

## Current strengths

The product is already more than a basic retrieve-and-generate RAG system. It
has a LangGraph research flow with planning, iterative retrieval, hybrid dense
and full-text search, reciprocal-rank fusion, reranking, citation persistence,
checkpoints, asynchronous ingestion, model-provider fallback, and an offline
evaluation harness.

The opportunity is to turn those components into a deliberate, budgeted, and
measurable decision system.

## Highest-impact improvements

| Priority | Improvement | Main benefit | Implementation principle |
| --- | --- | --- | --- |
| 1 | Evaluation baseline and CI regression gate | Quality and reliability | Measure recall, citation coverage/correctness, grounded claims, p95 latency, tokens, and cost on a golden set. |
| 2 | Semantic and retrieval-result caches | Lower cost and latency | Cache only safe, workspace-scoped results; invalidate when source documents change; track hit rate and quality. |
| 3 | Strict context budget and context selection | Lower token cost; better answers | Select fewer, stronger chunks; preserve citation identifiers; order evidence to reduce lost-in-the-middle effects. |
| 4 | Model routing | Lower model cost | Use smaller models for planning, query rewrite, verification, and summarisation; reserve the strongest model for final synthesis. |
| 5 | Rerank measurement and tuning | Better quality per millisecond | Use retrieval ablation to prove reranking lifts nDCG/citation quality; lower candidate counts or bypass it when it does not. |
| 6 | Uniform run/tool/provider budgets | Reliability and predictable spend | Enforce wall-clock, token, tool-call, and cost limits; fail safely with a grounded refusal rather than timing out. |
| 7 | Circuit breakers and structured retries | Better availability and tail latency | Stop calling unhealthy providers; retry only transient failures with bounded exponential backoff and jitter. |
| 8 | Ingestion retries and dead-letter handling | Operational reliability | Make failed ingestion jobs recoverable, idempotent, and observable. |
| 9 | Conversation summaries | Lower multi-turn cost; better continuity | Summarise durable context after a run instead of sending an unbounded raw message history. |

## Recommended delivery order

1. Establish a benchmark dashboard and a small golden dataset.
2. Enable and validate semantic caching, then add a workspace-scoped
   retrieval-result cache.
3. Add a hard context-token budget and evaluate the quality/cost trade-off.
4. Route bounded, low-risk graph nodes to lower-cost models.
5. Tune or remove expensive retrieval stages using ablation results.
6. Introduce verification and retries only if evaluation shows grounding—not
   retrieval—is the dominant failure mode.

The first five steps should reduce average cost and latency while retaining or
improving answer quality. They are more valuable than adding multiple agents.

## Agentic evolution: make every extra decision earn its cost

Simple factual questions should remain cheap:

```text
question -> retrieve -> synthesize -> cited answer
```

Only complex, ambiguous, or weakly supported questions should activate extra
reasoning:

```text
question -> plan/query analysis -> retrieve or safe tool use
         -> evidence verification -> synthesize -> cited answer
         -> post-run memory summary
```

### Appropriate forms of intelligence

| Component | Form | Reason |
| --- | --- | --- |
| Query analysis and plan | Bounded LangGraph node | Produces validated structured data; no independent agent persona required. |
| Retrieval | Deterministic service | Keeps search reproducible and testable. |
| Researcher | Tool-using agent | Appropriate when tool choice and bounded iteration require model judgment. |
| Verification | Cheap bounded node | Checks faithfulness, evidence coverage, and conflicting sources; may request one bounded retry. |
| Synthesis | Bounded node | Produces a final grounded response from verified evidence. |
| Memory writer | Post-run node/event | Writes a compact conversation summary; not an autonomous agent. |

Use at most one retry for a verification failure initially. Detect repeated
identical tool calls and stop rather than paying for an unproductive loop.

## High-value agentic capabilities

- **Evidence verification:** reject or qualify claims without adequate chunk
  support, and clearly surface conflicting sources.
- **Query decomposition:** break multi-part questions into a small number of
  independently retrievable sub-questions, then fuse results.
- **Governed external research:** a typed tool gateway for web search, safe URL
  fetch, and calculator use when the internal knowledge base lacks evidence.
  Enforce tool permissions, timeouts, result-size limits, schema validation,
  rate limits, and SSRF/prompt-injection defences.
- **Research brief mode:** create a cited report with evidence table, open
  questions, confidence, and source conflicts.
- **Comparison and gap analysis:** compare documents or repositories, identify
  missing requirements, and produce an implementation checklist.
- **Durable conversational continuity:** recall compact session summaries and,
  only after demonstrated need, add searchable semantic memory.

## Guardrails and decision rules

- Do not add agents merely to split a linear workflow. Prefer deterministic or
  bounded graph nodes.
- Every tool and agent step needs a timeout, token/cost budget, trace, and
  measurable success criterion.
- Retrieved and external content is untrusted data, never instructions.
- Preserve citations through every transformation; a response with inadequate
  evidence must refuse or explicitly qualify its conclusion.
- Add no new agent without a specification under `docs/specs/`, and add no new
  dependency without an ADR, following the repository rules.

## Definition of success

The project is meaningfully agentic when it can choose a bounded next action,
use authorised tools when internal evidence is insufficient, verify the
result, recover or refuse safely, remember relevant prior context, and show
that these behaviours improve quality per unit of cost and latency.
