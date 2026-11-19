/**
 * features/devicehub/utils/telemetry.ts
 * -------------------------------------
 * Purpose:    Narrowing and merging helpers for telemetry frames. The SSE
 *             stream mixes telemetry, status, and heartbeat payloads under a
 *             single `device.state` event name.
 * Dependencies: features/devicehub/types.ts
 * Scope:      Dashboard views.
 */

import type {
  ChartPoint,
  StreamPayload,
  TelemetryPayload,
  TelemetryRow,
} from "@/features/devicehub/types";

export function isTelemetryPayload(
  payload: StreamPayload,
): payload is TelemetryPayload {
  const candidate = payload as Partial<TelemetryPayload>;
  return typeof candidate.seq === "number" && typeof candidate.boot_id === "string";
}

/** Stable identity of a frame, used to dedupe replayed SSE events. */
export function frameKey(bootId: string, seq: number): string {
  return `${bootId}:${seq}`;
}

export function rowToPoint(row: TelemetryRow): ChartPoint {
  return {
    ts: Date.parse(row.ts),
    distance: row.distance_cm,
    l: row.line_l,
    c: row.line_c,
    r: row.line_r,
  };
}

export function payloadToPoint(payload: TelemetryPayload): ChartPoint {
  return {
    ts: Date.parse(payload.ts),
    distance: payload.distance_cm ?? null,
    l: payload.line?.l ?? null,
    c: payload.line?.c ?? null,
    r: payload.line?.r ?? null,
  };
}

/**
 * Merge historical rows (newest first from the API) with live frames,
 * dedupe by `(boot_id, seq)` and return the trailing window in time order.
 */
export function mergePoints(
  rows: TelemetryRow[],
  live: TelemetryPayload[],
  window: number,
): ChartPoint[] {
  const byKey = new Map<string, ChartPoint>();

  for (const row of rows) {
    byKey.set(frameKey(row.boot_id, row.seq), rowToPoint(row));
  }
  for (const payload of live) {
    byKey.set(frameKey(payload.boot_id, payload.seq), payloadToPoint(payload));
  }

  return [...byKey.values()]
    .sort((a, b) => a.ts - b.ts)
    .slice(-window);
}

/** One row of the "recent frames" table. */
export interface FrameRow {
  key: string;
  ts: number;
  seq: number;
  distance: number | null;
  l: number | null;
  c: number | null;
  r: number | null;
  motion: string | null;
}

function rowToFrame(row: TelemetryRow): FrameRow {
  return {
    key: frameKey(row.boot_id, row.seq),
    ts: Date.parse(row.ts),
    seq: row.seq,
    distance: row.distance_cm,
    l: row.line_l,
    c: row.line_c,
    r: row.line_r,
    motion: row.motion_state,
  };
}

function payloadToFrame(payload: TelemetryPayload): FrameRow {
  return {
    key: frameKey(payload.boot_id, payload.seq),
    ts: Date.parse(payload.ts),
    seq: payload.seq,
    distance: payload.distance_cm ?? null,
    l: payload.line?.l ?? null,
    c: payload.line?.c ?? null,
    r: payload.line?.r ?? null,
    motion: payload.motion?.state ?? null,
  };
}

/** Same merge as `mergePoints`, newest first, for the event log. */
export function mergeFrames(
  rows: TelemetryRow[],
  live: TelemetryPayload[],
  limit: number,
): FrameRow[] {
  const byKey = new Map<string, FrameRow>();

  for (const row of rows) {
    byKey.set(frameKey(row.boot_id, row.seq), rowToFrame(row));
  }
  for (const payload of live) {
    byKey.set(frameKey(payload.boot_id, payload.seq), payloadToFrame(payload));
  }

  return [...byKey.values()].sort((a, b) => b.ts - a.ts).slice(0, limit);
}
