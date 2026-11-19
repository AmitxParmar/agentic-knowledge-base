# ADR-0005: Deterministic safety; the LLM can only request
Status: Accepted · Date: 2026-11-13

## Context
A physical robot can cause harm or damage. LLM output is non-deterministic and vulnerable to prompt injection.

## Decision
- Motor control, thresholds and safety limits are deterministic code on the MCU and in the Rust policy gate.
- The agent can only call `request_command`, which creates a command in the normal lifecycle.
- Commands come from a fixed catalog with typed, ranged parameters; there are no raw motor or pin commands.
- Consequential commands need human approval; the backend re-validates after approval; the bridge and firmware validate again.
- Risk-reducing commands (`stop`, `estop`) may auto-approve.

## Alternatives considered
- Let the agent execute low-risk actions autonomously: faster, but unnecessary for the goals and increases risk.
- Human approval only: a single control that fails if the UI or approver errs.

## Consequences
+ Defense in depth; safety does not depend on model behavior.
− Slower remediation for consequential actions.
Risk: approval fatigue. Mitigation: clear evidence and diff in the approval UI; limit what is consequential.

## Revisit when
Never relaxed for the physical robot; for simulated devices a separate policy tier could be considered.
