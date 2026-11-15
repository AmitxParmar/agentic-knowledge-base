# EVENT_CONTRACTS

MQTT topics, payloads, versions and command schemas. Payload fields for the robot are provisional until the hardware inventory is done `[HW-TBD]`; the envelope and rules are stable.

## 1. Conventions

- Transport: MQTT over TLS, JSON payloads (UTF-8) in v1 ([ADR-0010](adr/0010-json-payloads-v1.md)).
- Topic prefix `dh/v1/`. The `v1` is the **topic-contract** version; each payload also carries its own `schema_version`.
- **The tenant is never in the topic or payload.** The backend resolves tenant from the authenticated device identity ([ADR-0009](adr/0009-tenant-isolation-rls.md)).
- MQTT username = `d_<device_id>`; broker ACLs use the `%u` pattern, so a device can only touch its own topics.
- IDs are UUIDs (v7 for server-generated). Timestamps are RFC 3339 UTC strings unless named `*_ms`.
- Unknown fields must be ignored by consumers. Removing or re-typing a field requires a new `schema_version`.

## 2. Topics

`{id}` is the device UUID.

| Topic | Dir | QoS | Retained | Purpose |
|---|---|---|---|---|
| `dh/v1/d/{id}/telemetry` | device → hub | 1 | no | Periodic sensor/state readings |
| `dh/v1/d/{id}/status` | device → hub | 1 | **yes** | `online`/`offline` presence; offline is the **Last Will** |
| `dh/v1/d/{id}/event` | device → hub | 1 | no | Discrete device-side events (obstacle, stop, fault) |
| `dh/v1/d/{id}/cmd` | hub → device | 1 | no | Command delivery |
| `dh/v1/d/{id}/ack` | device → hub | 1 | no | Command acknowledgment and execution status |
| `dh/v1/d/{id}/cfg` | hub → device | 1 | **yes** | Desired configuration (latest wins) |
| `dh/v1/d/{id}/cfg/ack` | device → hub | 1 | no | Applied/rejected configuration |

Broker ACL (per device):
```
publish:   dh/v1/d/<id>/telemetry, status, event, ack, cfg/ack
subscribe: dh/v1/d/<id>/cmd, cfg
```
Hub services use separate service credentials with wildcard read on device topics and write on `cmd` and `cfg`. Shared subscription for horizontal ingest: `$share/ingest/dh/v1/d/+/telemetry`.

## 3. Common envelope fields

| Field | Type | Notes |
|---|---|---|
| `schema_version` | int | Payload schema version |
| `device_id` | uuid | Must match the topic; mismatch → dead letter |
| `boot_id` | uuid | New on every device (or bridge) boot |
| `seq` | uint64 | Monotonic within a `boot_id`, starts at 1 |
| `ts` | RFC 3339 | Best-known event time (bridge-corrected) |
| `ts_mono_ms` | uint64 | Milliseconds since boot, from the MCU clock |

**Ordering and dedupe key:** `(device_id, boot_id, seq)`. Ordering across reboots uses `ts`; within a boot it uses `seq`.

## 4. `telemetry` v1

```json
{
  "schema_version": 1,
  "device_id": "0192f3c4-1a2b-7c3d-8e4f-5a6b7c8d9e0f",
  "boot_id":   "0192f3c4-0000-7000-8000-000000000001",
  "seq": 18422,
  "ts": "2026-11-13T09:15:02.481Z",
  "ts_mono_ms": 921440,
  "fw_version": "0.1.0",
  "distance_cm": 23.4,
  "line": { "l": 120, "c": 860, "r": 130 },
  "motion": { "state": "forward", "left_pwm": 140, "right_pwm": 140 },
  "power": { "battery_mv": 7400 },
  "config_version": 3
}
```

| Field | Type | Rules |
|---|---|---|
| `distance_cm` | float \| null | `null` = no echo/timeout. Valid range 2–400 `[HW-TBD]`; outside → still stored, rule may flag |
| `line.{l,c,r}` | int | Raw sensor readings; range depends on sensor type `[HW-TBD]` |
| `motion.state` | enum | `idle`, `forward`, `turn_left`, `turn_right`, `stopped`, `estop` |
| `motion.*_pwm` | int | −255..255 |
| `power.battery_mv` | int \| absent | Only if hardware supports it |
| `config_version` | int | Last applied config version |

Expected rate: 5–20 Hz for the robot *(initial)*; simulator is configurable. Payload ≤ 512 bytes.

**Validation outcomes**

| Case | Action |
|---|---|
| Valid, new `(boot_id, seq)` | Accept, batch to stores |
| Duplicate key | Drop, count `duplicates_total` |
| Older `seq` within the same boot than `last_seq` | Store history; do **not** update latest state |
| Gap in `seq` | Accept; count `seq_gaps_total` (loss indicator) |
| `ts` far in the future/past (beyond skew window) | Accept with `ts` clamped to `ingested_at`; flag `clock_skew` |
| Unknown `schema_version` | Dead letter `unsupported_version` |
| Malformed JSON / schema failure / oversize | Dead letter with reason |
| Topic device ≠ payload device | Dead letter `identity_mismatch` |

## 5. `status` (retained, with Last Will)

Online (published on connect):
```json
{ "schema_version": 1, "state": "online", "boot_id": "…", "fw_version": "0.1.0", "ts": "…" }
```
Last Will (broker publishes on unclean disconnect):
```json
{ "schema_version": 1, "state": "offline", "reason": "unclean_disconnect" }
```
`hub-worker` also marks a device offline when no telemetry or status is seen for `heartbeat_timeout` (default 15 s *(initial)*).

## 6. `event` v1 (device-side discrete events)

```json
{ "schema_version": 1, "device_id": "…", "boot_id": "…", "seq": 18430, "ts": "…",
  "type": "obstacle_stop", "severity": "warning",
  "data": { "distance_cm": 11.2, "threshold_cm": 15 } }
```
`type` ∈ `obstacle_stop`, `comms_loss_stop`, `estop_engaged`, `sensor_fault`, `brownout`, `watchdog_reset`. Events share the `seq` space with telemetry or use their own counter; v1 uses **its own counter** per topic to avoid coupling.

## 7. Commands

### 7.1 Catalog (v1)

| `type` | Params | Risk | Approval | Device effect |
|---|---|---|---|---|
| `stop` | none | risk-reducing | auto | Stop motors, hold |
| `estop` | none | risk-reducing | auto | Stop and latch until `reset_estop` |
| `reset_estop` | none | consequential | human | Clear latch (motors remain stopped) |
| `resume_line_follow` | `max_speed_pct` (0–60) | consequential | human | Resume line following under the cap |
| `set_speed_limit` | `max_speed_pct` (0–60) | consequential if increasing, else risk-reducing | human if increasing | Change cap |
| `request_diagnostics` | `scope` ∈ `sensors`,`motors`,`all` | risk-reducing | auto | Run a read-only self-test, return in `event` |
| `ping` | none | risk-reducing | auto | Echo ack |

There is **no** command that sets raw motor outputs or arbitrary pins. Hard limits (max speed, max run duration, obstacle threshold) are compiled into firmware and cannot be raised by any command. Limits shown here are provisional `[HW-TBD]`.

### 7.2 `cmd` payload

```json
{
  "schema_version": 1,
  "command_id": "0192f3c9-7d10-7a2e-9b11-2f3e4d5c6b7a",
  "device_id": "…",
  "type": "resume_line_follow",
  "params": { "max_speed_pct": 40 },
  "issued_at": "2026-11-13T09:16:00Z",
  "expires_at": "2026-11-13T09:16:30Z",
  "target_boot_id": "0192f3c4-0000-7000-8000-000000000001",
  "sig": "base64(hmac-sha256(device_command_key, canonical_json_without_sig))"
}
```

Rules:
- Device (or bridge) rejects when `now > expires_at` (with bounded skew tolerance), `target_boot_id` ≠ current `boot_id`, signature invalid, `type` unknown, or params out of range.
- Duplicate `command_id` re-delivery returns the previous ack without re-executing.
- A command accepted by firmware is executed at most once.
- The `sig` field defends against a compromised broker path or a forged publisher. Key per device, rotated with credentials ([SECURITY §3](SECURITY.md#3-device-identity-and-command-integrity)).

### 7.3 `ack` payload

```json
{
  "schema_version": 1, "command_id": "…", "device_id": "…", "boot_id": "…",
  "status": "received",
  "ts": "…", "reason": null, "result": null
}
```
`status` progression: `received` → `executing` → `completed` | `failed`, or terminal `rejected` (with `reason` ∈ `expired`, `stale_boot`, `bad_signature`, `unknown_type`, `out_of_range`, `estop_latched`, `busy`).

Hub state mapping: `received`→`acked`, `executing`→`executing`, `completed`/`failed`/`rejected`→terminal.

## 8. Configuration

`cfg` (retained):
```json
{ "schema_version": 1, "config_version": 4,
  "config": { "telemetry_hz": 10, "obstacle_threshold_cm": 15, "max_speed_pct": 50 },
  "issued_at": "…", "sig": "…" }
```
`cfg/ack`:
```json
{ "schema_version": 1, "config_version": 4, "status": "applied", "reason": null, "ts": "…" }
```
`status` ∈ `applied`, `rejected` (`out_of_range`, `unsupported_key`, `stale_version`). Safety-critical bounds (maximum speed, minimum obstacle threshold) are clamped by firmware regardless of config.

## 9. Serial framing (bridge ⇄ Arduino) `[HW-TBD]`

Between the MCU and bridge, messages are length-prefixed, COBS-framed, with CRC-16. The MCU sends compact telemetry frames; the bridge adds `device_id`, `ts` (clock-offset corrected), JSON-encodes, and publishes. Commands travel the other direction as binary frames after the bridge verifies `sig`, `expires_at`, `target_boot_id`, and the allow-list. Frame layout is defined in `firmware/PROTOCOL.md` when the board is chosen.

## 10. Agent ↔ hub events

`POST /internal/agent-events` (HMAC-signed, from `agent-service`):

```json
{ "run_id": "…", "incident_id": "…", "seq": 7, "at": "…",
  "kind": "tool_call",            // step_started | tool_call | tool_result | evidence | citation | diagnosis | command_requested | failed | completed
  "data": { "tool": "get_telemetry_window", "args": { "minutes": 5 }, "ok": true } }
```
Events are forwarded to the browser over SSE, keyed by `run_id`, with monotonic `seq` for resume.

## 11. Browser SSE streams

`GET /v1/stream?topics=fleet,device:{id},incident:{id}` returns `text/event-stream` with `id:` set to a per-stream monotonic cursor. Event names: `device.state`, `device.presence`, `incident.updated`, `agent.event`, `command.updated`. Clients reconnect with `Last-Event-ID`; if the cursor is too old the server sends `resync` and the client refetches.

## 12. Versioning policy

- Additive, optional fields: no version bump.
- Breaking change: new `schema_version`; ingest supports N and N−1 for at least one release; dead-letter counters alert on unsupported versions.
- JSON Schemas live in `crates/common/schemas/` and are used by Rust (validation), Python (tool models), TypeScript (types), and contract tests.
- A topic-contract change (`dh/v2/`) runs alongside v1 until all devices migrate.
