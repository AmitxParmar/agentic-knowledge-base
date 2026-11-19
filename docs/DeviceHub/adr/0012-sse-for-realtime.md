# ADR-0012: Server-Sent Events for browser realtime
Status: Accepted · Date: 2026-11-13

## Context
The dashboard needs one-way live updates: telemetry, presence, incidents, command status, agent progress. Client-to-server actions are ordinary HTTP requests.

## Decision
Use SSE from `hub-api` with per-client bounded queues, tenant-filtered topics, monotonic event IDs and `Last-Event-ID` resume; a `resync` event tells clients to refetch when the cursor is too old. Slow consumers are dropped. High-rate telemetry is coalesced server-side per device (e.g. latest value every 250 ms) before fan-out.

## Alternatives considered
- WebSocket: bidirectional but unneeded; more infrastructure and reconnection logic.
- Polling: simple, wasteful, worse latency.

## Consequences
+ Simple, proxy-friendly, native browser reconnect.
− One-directional; per-origin connection limits on HTTP/1.1.
Mitigation: multiplex topics on one stream; HTTP/2.

## Revisit when
The UI needs low-latency bidirectional control (e.g. live teleoperation), which is a non-goal.
