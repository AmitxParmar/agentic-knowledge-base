# ADR-0015: Rust and host dependencies for the device plane

Status: Accepted · Date: 2026-11-17

## Context

`AGENTS.md` rule 6 forbids new dependencies without a decision record. ADR-0001 and ADR-0002 already name the Rust runtime and framework, and ADR-0003 names the broker, but they do not enumerate the crates the telemetry slice needs. The serial bridge also needs a language decision: `SERVICE_BOUNDARIES.md` lists it as "Rust (or Python)".

Phase 2 adds one crate tree (`crates/common`, `apps/hub`) and, from T8, a host bridge.

## Decision

### Rust crates

| Crate | Used for | Why this one |
|---|---|---|
| `tokio` | async runtime, timers, broadcast channel | Named by ADR-0001; `current_thread` flavour on the free tier |
| `axum` | HTTP API, SSE | Named by ADR-0001; SSE is a first-class response type |
| `tower-http` | CORS, request tracing | Companion to axum; no custom middleware needed |
| `sqlx` (postgres, runtime-tokio, tls-rustls, chrono, uuid, json, migrate, macros) | pool, queries, embedded migrations | Named by ADR-0002; runtime-checked queries avoid a build-time database |
| `rumqttc` | MQTT client | Pure Rust, async, no C toolchain; alternate `paho-mqtt` needs the Eclipse C library |
| `serde`, `serde_json` | wire contracts | Contract v1 is JSON (ADR-0010) |
| `uuid` | device, boot, tenant ids | UUIDv7-compatible; matches `DATA_MODEL.md` |
| `chrono` | `timestamptz` and RFC 3339 | Direct mapping to Postgres timestamps |
| `async-stream` | SSE event stream | Small, avoids hand-writing a `Stream` impl |
| `tracing`, `tracing-subscriber` | structured logs | Matches the observability style of the Python service |
| `thiserror`, `anyhow` | typed config/wire errors, binary `main` | Keeps library errors typed and binaries terse |
| `dotenvy` | local `.env` loading | Same ergonomics as `pydantic-settings`; never used in production |

### Host bridge (T8)

The bridge is **Rust**, superseding the "Python is acceptable" option in `SERVICE_BOUNDARIES.md`.

- `serialport` for the USB serial port, read on a dedicated blocking thread.
- `rumqttc` reusing the same MQTT client stack as the hub.
- Build prerequisite on Linux: `libudev-dev` and `pkg-config` (a `serialport` dependency).
- `apps/bridge` is excluded from `default-members` so a plain `cargo build` at the repo root does not require libudev.

Rationale: the bridge holds the device credential and, from Phase 5, verifies command signatures and enforces an allow-list. That is trust-boundary code, and it belongs in the typed language the rest of the device plane already uses. Writing it in Python would mean rewriting it when commands arrive.

### Rejected

- `paho-mqtt` (Rust binding): pulls the Eclipse C library into the build for no capability gain.
- `testcontainers`: convenient, but adds a heavy dev dependency for two integration tests; CI service containers cover it.
- `tokio-serial`: async wrapper over `serialport` with no benefit at 5–20 Hz; a blocking thread is simpler.
- Python bridge: faster to write once, but a guaranteed rewrite at the command phase.

## Consequences

- One Rust toolchain builds the hub and the bridge; the mobile-side firmware stays C++ (Arduino), which is not a Rust target in practice.
- `cargo build` at the root needs no system packages; `cargo build -p devicehub-bridge` needs `libudev-dev`.
- Versions are pinned by `Cargo.lock`, which is committed.
- Dependency review for later phases must extend this table rather than adding crates ad hoc.
