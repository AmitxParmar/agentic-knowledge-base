# ADR-0007: Command delivery via transactional outbox, idempotency and expiry
Status: Accepted · Date: 2026-11-13

## Context
Commands move a physical device. Duplicates, lost commands and late execution are unacceptable. Publishing to MQTT and updating the database cannot be one atomic operation.

## Decision
- Create a command and its outbox row in one PostgreSQL transaction; the dispatcher claims rows with `FOR UPDATE SKIP LOCKED` and publishes.
- Idempotency: `unique(tenant_id, idempotency_key)` for creation; `command_id` deduplicated by device/bridge for execution.
- Expiry: every command has `expires_at`; checked by hub, bridge and firmware.
- Boot binding: `target_boot_id` rejects commands for a previous boot.
- Signatures: HMAC with per-device key.
- Offline devices: commands stay `queued` until expiry.

## Alternatives considered
- Publish directly from the API handler: dual-write inconsistency on crash.
- Retained command topic: replays old commands after reconnect.
- Exactly-once broker semantics: not available.

## Consequences
+ No lost commands, no double execution in crash-injection tests, auditable lifecycle.
− Extra moving part (dispatcher) and polling latency.
Mitigation: `LISTEN/NOTIFY` to wake the dispatcher; emergency stop uses a high-priority immediate path.

## Revisit when
Dispatch latency is a measured issue.
