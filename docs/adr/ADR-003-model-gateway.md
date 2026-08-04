# ADR-003: Model Gateway Pattern — MVP Implementation via LM Studio

**Status:** Accepted
**Date:** 2026-06-22
**Deciders:** Project architecture (frozen V1 design) + MVP scoping

## Context
Every LLM call — query rewrite, the Research Agent's reasoning — should go
through one internal interface instead of agent code calling a provider SDK
directly. That decouples "which model serves this call" from "how the agent
calls it," so the backend can change without touching agent code.

The V1 architecture names LiteLLM as the Model Gateway's concrete
implementation, routing to Ollama by default with OpenAI-compatible failover
to a hosted provider. The MVP scope intentionally simplifies the *backend*
behind that same interface without abandoning the pattern.

## Decision
Keep the **Model Gateway as an abstraction** — all model calls go through
one internal interface, never a provider SDK directly. For the MVP, that
interface's only configured backend is **LM Studio**, running locally and
exposing an OpenAI-compatible endpoint, serving a 3B–4B instruction model
(Qwen3 4B or Gemma 3 4B). LiteLLM, OpenRouter, or a hosted provider can be
swapped in later as the same interface's backend — that swap is the entire
point of having the abstraction.

This is a deliberate MVP-phase simplification of the V1 architecture's
Model Gateway, the same way the V1 design's Planner and Critic agents are
deferred in `PRD.md`. The interface boundary the V1 design specifies is
preserved; only the concrete backend behind it is simpler for now.

## Options Considered

### Option A: Call LM Studio's API directly from agent code
| Dimension | Assessment |
|---|---|
| Complexity | Lowest — no abstraction layer to build |
| Cost | None |
| Scalability | Breaks immediately on any future provider swap — every call site needs editing |
| Team familiarity | High |

**Pros:** Fastest to write today.
**Cons:** Violates the V1 architecture's explicit principle that agents
never call a model backend directly — exactly the coupling the Model
Gateway exists to prevent.

### Option B: Adopt LiteLLM now, as the V1 design specifies
| Dimension | Assessment |
|---|---|
| Complexity | Medium — another service to configure correctly |
| Cost | None (open source) |
| Scalability | Matches the full V1 design exactly |
| Team familiarity | Low |

**Pros:** No future migration needed; matches the frozen architecture
diagram exactly.
**Cons:** Pulls in routing/failover machinery the MVP — one local model,
single backend — has no use for yet. Premature relative to `PRD.md` scope.

### Option C: Thin internal Model Gateway interface, LM Studio as the only backend
| Dimension | Assessment |
|---|---|
| Complexity | Low — a small interface, one implementation |
| Cost | None |
| Scalability | Swapping to LiteLLM/OpenRouter/hosted later means writing a new backend behind the same interface, not editing call sites |
| Team familiarity | High — LM Studio is simple to run locally |

**Pros:** Gets the decoupling benefit the architecture wants, without
LiteLLM's routing complexity before there's more than one backend to route
between.
**Cons:** The interface itself is a small amount of extra code that Option
A skips.

## Trade-off Analysis
Option A is rejected outright — it violates a stated architecture
principle, not just a style preference. Between B and C: LiteLLM's value is
routing across *multiple* backends, which doesn't exist yet at MVP scale.
Option C gets the same decoupling with less moving infrastructure, and
upgrading to LiteLLM later is a backend swap, not a redesign.

## Consequences
- Easier: chat model and embedding/rerank models can change independently —
  the gateway interface only covers chat/completion calls, not BGE-M3 or
  BGE-Reranker-v2-m3, which run as separate self-hosted models per
  `conventions.md`
- Easier: future move to LiteLLM/OpenRouter/hosted providers is additive
- Harder: no automatic failover or multi-backend routing exists yet — if
  LM Studio is down, there is no fallback in MVP
- Revisit: once more than one backend is actually needed (e.g., a hosted
  fallback), migrate the gateway's implementation to LiteLLM rather than
  hand-rolling multi-backend routing

## Action Items
1. [ ] Define the Model Gateway as a single internal interface
   (`generate(messages, …)`-style) used by the Research Agent and query
   rewrite step — never call LM Studio's endpoint from agent code directly
2. [ ] Configure LM Studio with a 3B–4B instruction model as the only
   backend behind that interface for MVP

## Update (2026-08-04): LiteLLM replaces the hand-rolled backend

The Model Gateway interface (`complete()` / `complete_with_tools()`) is
**unchanged** — all call sites in the Research Agent, retrieval pipeline, and
`/test-llm` still compile against the same signatures.

The concrete implementation now delegates to **LiteLLM** instead of a
hand-rolled provider loop. LiteLLM owns provider routing, retries, and the
Groq → OpenRouter fallback chain. This replaces ~140 lines of provider
client-management code with a single `litellm.acompletion()` call.

### What changed

- Implementation behind the interface swapped from manual provider chain to
  LiteLLM (`src/shared/model_gateway.py`).
- `settings.py`: removed provider-specific `MODEL_GATEWAY_GROQ_BASE_URL` and
  `MODEL_GATEWAY_OPENROUTER_BASE_URL` — LiteLLM derives endpoints from the
  `provider/model` prefix. API keys and model names remain in Settings and
  are bridged into env for LiteLLM.
- `pyproject.toml`: `groq` and direct `openai` pins replaced by `litellm`
  (which bundles OpenAI-compatible clients for both providers).

### Why now

The ADR originally deferred LiteLLM because MVP had a single backend. That
precondition changed — a hosted fallback (OpenRouter) is now required for
the deployed/demo environment, exactly the "multiple backends" trigger the
ADR named for revisiting the gateway's implementation.

### Consequences

- Easier: adding a third provider is a model string + API key, not new
  routing code.
- Easier: retries and failover are handled by LiteLLM's controllers.
- Harder: a single cloud dependency (`litellm`) now owns provider behavior;
  upgrades must be reviewed.
- Unchanged: the interface boundary (ADR's core point) still protects
  callers from provider specifics.
