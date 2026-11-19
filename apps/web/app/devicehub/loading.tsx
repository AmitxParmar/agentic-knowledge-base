/**
 * app/devicehub/loading.tsx
 * -------------------------
 * Purpose:    Route-level placeholder while the fleet view mounts.
 * Dependencies: dashboard-state
 * Scope:      /devicehub
 */

import { LoadingPanel } from "@/features/devicehub/components/dashboard-state";
import styles from "./devicehub.module.css";

export default function DeviceHubLoading() {
  return (
    <main className={styles.page}>
      <LoadingPanel label="Loading fleet…" />
    </main>
  );
}
