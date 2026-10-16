# ADR-010: Input/Output Guardrails

**Status:** Accepted
**Date:** 2026-09-28
**Deciders:** AI-product hardening plan (docs/REMAINING.md:90,222 deferred items)

## Context
The research pipeline takes untrusted input (user questions, chat history,
uploaded document text that reaches the model as context) and returns model
output to the client. Two deferred items require guardrails: input scanning
(LLM Guard was named) and output scanning (Guardrails AI was named). AGENTS.md
rule 6 requires an ADR before adding either dependency.

## Decision
Implement deterministic, dependency-free guardrails in
`src/shared/prompt_safety.py` (the existing prompt-boundary module): pattern
scanners for prompt-injection phrases and secret/credential shapes, with
redaction of secrets before text reaches the model or the client. No new
packages.

Behavior contract:
- **Input:** secrets redacted before the prompt is built (never send
  credentials to a provider); injection phrases flagged to telemetry only
  (no refusal — see Consequences).
- **Output:** secrets redacted before persist/cache/delivery; system-prompt
  leak filter (already shipped) blocks on hit.
- Kill-switch: `GUARDRAILS_ENABLED=false` disables scanning (sanitization
  length caps stay — those are structural, not guardrails).

## Options Considered

### Option A: LLM Guard (Protect AI)
| Dimension | Assessment |
|---|---|
| Detection quality | High — transformer-based detectors (injection, secrets, toxicity) |
| Cost | GB-sized model downloads, torch/transformers stack, slow cold start |
| Scalability | Needs GPU or patient CPU; hostile to the Render free-tier single container |
| Team familiarity | Low — new framework, new failure modes |

**Pros:** Best-in-class detection, maintained detectors.
**Cons:** Heavyweight runtime the current deployment cannot host; model
downloads at boot break the 60s cold-start story; overkill before traffic exists.

### Option B: Guardrails AI
| Dimension | Assessment |
|---|---|
| Detection quality | Medium — hub validators, rail specs, mixed local/remote execution |
| Cost | Framework + validator maintenance; some validators need API keys |
| Scalability | Lighter than LLM Guard but still a framework to operate |
| Team familiarity | Low |

**Pros:** Declarative rails, reusable validators.
**Cons:** Adds an operating framework for what is currently three regex
families; validator quality varies; project maintenance has been uneven.

### Option C: Deterministic DIY scanners (chosen)
| Dimension | Assessment |
|---|---|
| Detection quality | Medium — catches known phrase/shape families, misses novel attacks |
| Cost | Zero deps, microseconds per scan, fully CI-testable |
| Scalability | Trivially scalable (pure functions) |
| Team familiarity | High — extends the existing prompt_safety module |

**Pros:** No new dependencies (rule 6 satisfied trivially); fast, testable,
fits the deployment; covers the highest-frequency risks (credential echo,
classic injection phrases).
**Cons:** Pattern lists need curation as attacks evolve; no semantic
understanding — a paraphrased injection passes.

## Consequences
- Injection hits are telemetry-only (logfire warn), never refusals:
  legitimate questions *about* injections ("what does 'ignore previous
  instructions' mean?") must keep working; containment comes from the
  delimiter rules + tool-arg validation, not from blocking input.
- Secrets are redacted (input and output), never passed through — slight
  answer fidelity cost when a document legitimately contains a key-like
  string, accepted for safety.
- Revisit Option A when: sustained traffic justifies model hosting, or the
  DIY pattern list shows repeated misses in trace reviews.
