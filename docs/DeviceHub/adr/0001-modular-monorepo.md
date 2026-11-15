# ADR-0001: Modular monorepo with few deployable units
Status: Accepted · Date: 2026-11-13

## Context
One developer, many technologies (Rust, Python, TypeScript, C++). Early splitting into services adds network contracts, deployment work and debugging cost before there is any scaling evidence.

## Decision
One repository. Rust code is a Cargo workspace with shared crates. Initial deployable units: `hub-api`, `hub-worker`, `agent-service`, `web`, plus bridge, simulator and firmware. Logical components (ingest, rules, command service, realtime) live as modules inside the two Rust binaries.

## Alternatives considered
- Microservice per component: independent scaling, but heavy operational overhead and contract drift for a single maintainer.
- One Rust binary: simplest, but ingest load would compete with API latency and prevents independent restarts.

## Consequences
+ Fast refactoring, shared types and schemas, one CI pipeline.
− Module boundaries are enforced by convention and crate visibility, not the network.
Risk: boundary erosion. Mitigation: crate-level dependency rules checked in CI.

## Revisit when
Measurements show a component needs independent scaling or isolation (e.g. rules engine CPU affecting ingest p99).
