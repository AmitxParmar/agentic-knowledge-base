/**
 * app/devicehub/page.tsx
 * ----------------------
 * Purpose:    DeviceHub fleet view — every registered device with its
 *             presence and latest frame. Links into per-device telemetry.
 * Dependencies: use-devices.ts, dashboard-state, format.ts, devicehub.module.css
 * Scope:      DeviceHub presentation only; all data comes from apps/hub.
 */

"use client";

import Link from "next/link";
import { useDevices } from "@/features/devicehub/api/use-devices";
import {
  EmptyPanel,
  ErrorPanel,
  LoadingPanel,
} from "@/features/devicehub/components/dashboard-state";
import { formatAge, formatInteger, formatNumber } from "@/features/devicehub/utils/format";
import styles from "./devicehub.module.css";

function PresenceChip({ online }: { online: boolean }) {
  return (
    <span className={`${styles.chip} ${online ? styles.online : styles.offline}`}>
      <span className={styles.dot} aria-hidden="true" />
      {online ? "online" : "offline"}
    </span>
  );
}

export default function DeviceHubPage() {
  const { data, isPending, error, refetch, isFetching } = useDevices();

  const devices = data ?? [];
  const online = devices.filter((device) => device.online).length;

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Device plane</p>
          <h1 className={styles.title}>Fleet</h1>
          <p className={styles.subtitle}>
            Live and historical telemetry served by the DeviceHub hub.
          </p>
        </div>
        <button
          type="button"
          className={styles.refresh}
          onClick={() => void refetch()}
          disabled={isFetching}
        >
          {isFetching ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      {isPending ? <LoadingPanel label="Loading fleet…" /> : null}

      {!isPending && error ? (
        <ErrorPanel error={error} onRetry={() => void refetch()} />
      ) : null}

      {!isPending && !error && devices.length === 0 ? (
        <EmptyPanel
          title="No devices registered"
          detail="The hub's seed migration registers one bench device. Apply migrations, start the hub, then connect the board."
        />
      ) : null}

      {!isPending && !error && devices.length > 0 ? (
        <>
          <p className={styles.summary}>
            {devices.length} device{devices.length === 1 ? "" : "s"} ·{" "}
            {online} online
          </p>

          <ul className={styles.grid}>
            {devices.map((device) => {
              const telemetry = device.telemetry;
              return (
                <li key={device.id}>
                  <Link
                    href={`/devicehub/${device.id}`}
                    className={styles.card}
                  >
                    <div className={styles.cardHead}>
                      <div>
                        <h2 className={styles.cardTitle}>{device.name}</h2>
                        <p className={styles.cardId}>
                          {device.external_id} · {device.kind}
                        </p>
                      </div>
                      <PresenceChip online={device.online} />
                    </div>

                    <dl className={styles.metrics}>
                      <div className={styles.metric}>
                        <dt>Distance</dt>
                        <dd>{formatNumber(telemetry?.distance_cm ?? null)} cm</dd>
                      </div>
                      <div className={styles.metric}>
                        <dt>Line L / C / R</dt>
                        <dd>
                          {formatInteger(telemetry?.line?.l ?? null)} /{" "}
                          {formatInteger(telemetry?.line?.c ?? null)} /{" "}
                          {formatInteger(telemetry?.line?.r ?? null)}
                        </dd>
                      </div>
                      <div className={styles.metric}>
                        <dt>Battery</dt>
                        <dd>
                          {telemetry?.power?.battery_mv
                            ? `${formatInteger(telemetry.power.battery_mv)} mV`
                            : "—"}
                        </dd>
                      </div>
                    </dl>

                    <footer className={styles.cardFoot}>
                      <span>
                        {device.last_seen_at
                          ? `seen ${formatAge(device.last_seen_at)}`
                          : "never reported"}
                      </span>
                      <span className={styles.cardLink}>Telemetry →</span>
                    </footer>
                  </Link>
                </li>
              );
            })}
          </ul>
        </>
      ) : null}
    </main>
  );
}
