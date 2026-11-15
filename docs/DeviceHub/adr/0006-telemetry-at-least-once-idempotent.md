# ADR-0006: At-least-once telemetry with idempotent processing
Status: Accepted · Date: 2026-11-13

## Context
MQTT QoS 1 redelivers on reconnect. Bridges may replay buffered events. Devices reboot and clocks drift. Exactly-once delivery is not available end to end.

## Decision
Deliver at least once (QoS 1) and make processing idempotent. Event identity is `(device_id, boot_id, seq)`. The worker deduplicates in a bounded sliding window; ClickHouse `ReplacingMergeTree` with that key in the sorting key removes residual duplicates; latest state updates only for newer `(boot_id, seq)`. The worker acknowledges after enqueueing into a bounded stage. Overload policy: backpressure first, then shed oldest telemetry; never shed commands or acks.

## Alternatives considered
- QoS 0: lower overhead, silent loss.
- QoS 2: heavier protocol, still not end to end across the store.
- Persist every message synchronously before ack: simpler guarantees, much lower throughput.

## Consequences
+ Correctness under redelivery, replay and reconnect.
− Small window of loss if the worker crashes between ack and flush. Accepted for telemetry; counters expose gaps via `seq`.
Risk: window sizing. Mitigation: configurable and benchmarked.

## Revisit when
A telemetry type becomes safety-relevant (then use the command path semantics instead).
