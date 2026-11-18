/**
 * features/devicehub/types.ts
 * ---------------------------
 * Purpose:    Shapes returned by the DeviceHub read API (`apps/hub`).
 *             Mirrors `apps/hub/src/api/routes.rs` and
 *             `crates/common/src/wire.rs` — no logic, no defaults.
 * Dependencies: none (type-only; safe to import from client components)
 * Scope:      Dashboard types.
 */

/** `dh/v1/d/{id}/telemetry` payload, as stored in `payload`. */
export interface TelemetryPayload {
  schema_version: number;
  device_id: string;
  boot_id: string;
  seq: number;
  ts: string;
  ts_mono_ms?: number | null;
  fw_version?: string | null;
  distance_cm?: number | null;
  line?: { l: number; c?: number | null; r: number } | null;
  motion?: {
    state: string;
    left_pwm?: number | null;
    right_pwm?: number | null;
  } | null;
  power?: { battery_mv?: number | null } | null;
  config_version?: number | null;
}

/** `GET /v1/devices/{id}`. */
export interface DeviceSummary {
  id: string;
  external_id: string;
  name: string;
  kind: string;
  model: string | null;
  fw_version: string | null;
  status: string;
  last_seen_at: string | null;
  online: boolean;
  telemetry: TelemetryPayload | null;
  updated_at: string | null;
}

/** One row of `GET /v1/devices/{id}/telemetry` (newest first). */
export interface TelemetryRow {
  id: number;
  device_id: string;
  boot_id: string;
  seq: number;
  ts: string;
  ingested_at: string;
  distance_cm: number | null;
  line_l: number | null;
  line_c: number | null;
  line_r: number | null;
  motion_state: string | null;
  left_pwm: number | null;
  right_pwm: number | null;
  battery_mv: number | null;
  config_version: number | null;
  clock_skew: boolean;
  payload: TelemetryPayload;
}

/** `GET /v1/stream` — the `device.state` SSE event body. */
export interface DeviceStateEvent {
  /** Telemetry row id. `null` for status and sweep events. */
  id: number | null;
  device_id: string;
  ts: string;
  /** `null` means historical replay; do not infer presence from it. */
  online: boolean | null;
  /** Telemetry frames, `StatusV1`, or a heartbeat-offline notice. */
  payload: StreamPayload;
}

/**
 * The stream is not telemetry-only: status and heartbeat frames share the
 * same event name, so consumers must narrow before reading sensor fields.
 * `EVENT_CONTRACTS.md` §5.
 */
export interface StatusPayload {
  schema_version: number;
  state: "online" | "offline";
  ts?: string | null;
}

export type StreamPayload =
  | TelemetryPayload
  | StatusPayload
  | { state?: string; reason?: string };

/** A point plotted by the dashboard, in either units. */
export interface ChartPoint {
  ts: number;
  distance: number | null;
  l: number | null;
  c: number | null;
  r: number | null;
}
