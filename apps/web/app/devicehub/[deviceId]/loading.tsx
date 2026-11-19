/**
 * app/devicehub/[deviceId]/loading.tsx
 * ------------------------------------
 * Purpose:    Route-level placeholder while the device view mounts.
 * Dependencies: dashboard-state
 * Scope:      /devicehub/[deviceId]
 */

import { LoadingPanel } from "@/features/devicehub/components/dashboard-state";
import styles from "./detail.module.css";

export default function DeviceDetailLoading() {
  return (
    <main className={styles.page}>
      <LoadingPanel label="Loading device…" />
    </main>
  );
}
