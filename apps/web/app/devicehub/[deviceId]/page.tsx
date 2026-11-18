/**
 * app/devicehub/[deviceId]/page.tsx
 * ---------------------------------
 * Purpose:    Per-device view: latest readings, historical charts, and a
 *             live feed from the hub's SSE stream.
 * Dependencies: use-device, use-telemetry, use-device-stream, TelemetryChart
 * Scope:      DeviceHub presentation only. Ingestion and retention are
 *             untouched; this page is read-only.
 */

"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useDevice } from "@/features/devicehub/api/use-device";
import { useTelemetry, TELEMETRY_WINDOW } from "@/features/devicehub/api/use-telemetry";
import { TelemetryChart } from "@/features/devicehub/components/telemetry-chart";
import {
  EmptyPanel,
  ErrorPanel,
  LoadingPanel,
} from "@/features/devicehub/components/dashboard-state";
import {
  useDeviceStream,
  type StreamStatus,
} from "@/features/devicehub/hooks/use-device-stream";
import type { TelemetryPayload } from "@/features/devicehub/types";
import {
  formatAge,
  formatClock,
  formatDateTime,
  formatInteger,
  formatNumber,
} from "@/features/devicehub/utils/format";
import {
  frameKey,
  isTelemetryPayload,
  mergeFrames,
  mergePoints,
} from "@/features/devicehub/utils/telemetry";
import styles from "./detail.module.css";

/** Live frames retained in memory for the chart and the event log. */
const LIVE_WINDOW = 300;
const LOG_ROWS = 20;

function StreamBadge({
  status,
  lastAt,
}: {
  status: StreamStatus;
  lastAt: number | null;
}) {
  const label =
    status === "live"
      ? "stream live"
      : status === "reconnecting"
        ? "reconnecting"
        : status === "unsupported"
          ? "stream unsupported"
          : "connecting";

  return (
    <span
      className={`${styles.stream} ${status === "live" ? styles.streamLive : ""}`}
      title={lastAt ? `last frame ${formatClock(new Date(lastAt).toISOString())}` : undefined}
    >
      <span className={styles.dot} aria-hidden="true" />
      {label}
    </span>
  );
}

function Reading({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.reading}>
      <span className={styles.readingLabel}>{label}</span>
      <span className={styles.readingValue}>{value}</span>
    </div>
  );
}

export default function DeviceDetailPage() {
  const params = useParams<{ deviceId: string }>();
  const deviceId = typeof params.deviceId === "string" ? params.deviceId : "";

  const device = useDevice(deviceId);
  const history = useTelemetry(deviceId);
  const { status, event, lastAt } = useDeviceStream(deviceId.length > 0);

  const [live, setLive] = useState<TelemetryPayload[]>([]);

  // Live frames belong to one device; drop them when the route changes.
  useEffect(() => {
    setLive([]);
  }, [deviceId]);

  useEffect(() => {
    if (!event || event.device_id !== deviceId) return;
    if (!isTelemetryPayload(event.payload)) return;

    const incoming = event.payload;
    const key = frameKey(incoming.boot_id, incoming.seq);

    setLive((previous) => {
      const index = previous.findIndex(
        (frame) => frameKey(frame.boot_id, frame.seq) === key,
      );
      if (index >= 0) {
        // A replayed frame after reconnect: replace, never duplicate.
        const next = [...previous];
        next[index] = incoming;
        return next;
      }
      return [...previous, incoming].slice(-LIVE_WINDOW);
    });
  }, [event, deviceId]);

  const points = useMemo(
    () => mergePoints(history.data ?? [], live, TELEMETRY_WINDOW),
    [history.data, live],
  );

  const frames = useMemo(
    () => mergeFrames(history.data ?? [], live, LOG_ROWS),
    [history.data, live],
  );

  const latest: TelemetryPayload | null =
    live.length > 0
      ? (live[live.length - 1] ?? null)
      : (history.data?.[0]?.payload ?? device.data?.telemetry ?? null);

  const latestRow = history.data?.[0] ?? null;
  const clockSkew = latestRow?.clock_skew ?? false;

  if (device.isPending) {
    return (
      <main className={styles.page}>
        <LoadingPanel label="Loading device…" />
      </main>
    );
  }

  if (device.error) {
    return (
      <main className={styles.page}>
        <Link href="/devicehub" className={styles.back}>
          ← Fleet
        </Link>
        <ErrorPanel error={device.error} onRetry={() => void device.refetch()} />
      </main>
    );
  }

  if (!device.data) {
    return (
      <main className={styles.page}>
        <Link href="/devicehub" className={styles.back}>
          ← Fleet
        </Link>
        <EmptyPanel
          title="Device not found"
          detail="The hub has no device with this id."
        />
      </main>
    );
  }

  const summary = device.data;
  const telemetryError = history.error;

  return (
    <main className={styles.page}>
      <Link href="/devicehub" className={styles.back}>
        ← Fleet
      </Link>

      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{summary.kind}</p>
          <h1 className={styles.title}>{summary.name}</h1>
          <p className={styles.subtitle}>
            {summary.external_id}
            {summary.model ? ` · ${summary.model}` : ""}
            {summary.fw_version ? ` · fw ${summary.fw_version}` : ""}
          </p>
        </div>

        <div className={styles.headerMeta}>
          <span
            className={`${styles.chip} ${summary.online ? styles.online : styles.offline}`}
          >
            <span className={styles.dot} aria-hidden="true" />
            {summary.online ? "online" : "offline"}
          </span>
          <span className={styles.metaText}>
            last seen {formatAge(summary.last_seen_at)}
          </span>
          <StreamBadge status={status} lastAt={lastAt} />
        </div>
      </header>

      {clockSkew ? (
        <p className={styles.warning} role="status">
          The device clock was more than 5 minutes off; timestamps were clamped
          to ingest time for the newest frame.
        </p>
      ) : null}

      <section className={styles.readings} aria-label="Latest readings">
        <Reading label="Distance" value={`${formatNumber(latest?.distance_cm ?? null)} cm`} />
        <Reading label="Line L" value={formatInteger(latest?.line?.l ?? null)} />
        <Reading label="Line C" value={formatInteger(latest?.line?.c ?? null)} />
        <Reading label="Line R" value={formatInteger(latest?.line?.r ?? null)} />
        <Reading label="Motion" value={latest?.motion?.state ?? "—"} />
        <Reading
          label="Battery"
          value={
            latest?.power?.battery_mv
              ? `${formatInteger(latest.power.battery_mv)} mV`
              : "—"
          }
        />
        <Reading label="Sequence" value={latest ? String(latest.seq) : "—"} />
        <Reading label="Frame time" value={formatDateTime(latest?.ts ?? null)} />
      </section>

      {telemetryError ? (
        <ErrorPanel
          error={telemetryError}
          onRetry={() => void history.refetch()}
        />
      ) : null}

      {!telemetryError && points.length === 0 ? (
        <EmptyPanel
          title="No telemetry yet"
          detail="Start the bridge with the board connected. Frames appear here as the hub ingests them."
        />
      ) : null}

      {points.length > 0 ? (
        <section aria-label="Telemetry history">
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionTitle}>Telemetry</h2>
            <span className={styles.sectionMeta}>
              {points.length} samples · distance and line channels
            </span>
          </div>
          <TelemetryChart points={points} />
        </section>
      ) : null}

      {frames.length > 0 ? (
        <section aria-label="Recent frames">
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionTitle}>Recent frames</h2>
            <span className={styles.sectionMeta}>newest first</span>
          </div>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Seq</th>
                  <th scope="col">Dist (cm)</th>
                  <th scope="col">L</th>
                  <th scope="col">C</th>
                  <th scope="col">R</th>
                  <th scope="col">Motion</th>
                </tr>
              </thead>
              <tbody>
                {frames.map((frame) => (
                  <tr key={frame.key}>
                    <td>{formatClock(new Date(frame.ts).toISOString())}</td>
                    <td className={styles.mono}>{frame.seq}</td>
                    <td>{formatNumber(frame.distance)}</td>
                    <td>{formatInteger(frame.l)}</td>
                    <td>{formatInteger(frame.c)}</td>
                    <td>{formatInteger(frame.r)}</td>
                    <td>{frame.motion ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </main>
  );
}
