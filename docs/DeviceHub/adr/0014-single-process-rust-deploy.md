# ADR-0014: Deploy the Rust device plane as one process on Render's free tier

Status: Accepted · Date: 2026-11-16

## Context

ADR-0001 splits the device plane into `hub-api` and `hub-worker` as separate deployable units, so ingest load cannot compete with API latency.

The demo target is Render's free tier: 512 MB RAM, 0.1 CPU, 750 instance hours/month, no persistent disk, no background workers, HTTP(S) inbound only, and spin-down after inactivity. Two services would consume two instance-hour budgets and two cold starts, and a free-tier web service cannot host a raw MQTT listener at all.

## Decision

Keep the **logical** split (API and worker remain separate modules with separate responsibilities) but ship **one deployable process**.

- One crate at `apps/hub/` containing a library plus three binaries: `api`, `worker`, and `all`.
- `all` starts the API server and the MQTT ingest worker as two Tokio tasks in one process, on a **current-thread runtime** to stay inside the 512 MB / 0.1 CPU budget.
- Development may run `api` and `worker` separately; Render runs `all`.
- The process honours `$PORT` and binds `0.0.0.0`, as Render requires.
- Database pools stay small (≤ 5 connections) because Neon free tier limits connections and the instance is memory-constrained.

This does not change ownership, contracts, or the rule that Rust owns device truth and safety. It changes only the deployment unit count.

## Alternatives considered

- **Two Render services.** ADR-0001-faithful, but doubles instance-hour use, doubles cold starts, and free-tier background workers are not available.
- **One Render web service for the API plus a paid worker.** Costs money for a portfolio demo and buys nothing at demo scale.
- **Run the worker only on the laptop.** Keeps the free tier untouched, but the hosted deployment then shows no live data and the API cannot demonstrate ingest.

## Consequences

Positive:

- One deploy, one build, one cold start, one log stream.
- Fits free-tier CPU and memory.
- The logical boundary survives in code, so splitting back is a deployment change, not a rewrite.

Negative:

- A worker panic can take the API down with it; mitigate by supervising tasks and failing readiness.
- Ingest CPU shares 0.1 CPU with request handling; acceptable at 5–20 Hz for one device.
- Free-tier spin-down means the first request after idle is slow; accepted for a demo.

## Revisit when

The deployment moves off the free tier, ingest exceeds a single device at 20 Hz, or API p99 is measurably affected by ingest (ADR-0001's revisit trigger).
