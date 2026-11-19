/**
 * app/devicehub/error.tsx
 * -----------------------
 * Purpose:    Error boundary for the fleet route. Renders the same copy as
 *             the in-page error state so a render failure is not a dead end.
 * Dependencies: dashboard-state
 * Scope:      /devicehub
 */

"use client";

import { ErrorPanel } from "@/features/devicehub/components/dashboard-state";
import styles from "./devicehub.module.css";

export default function DeviceHubError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className={styles.page}>
      <ErrorPanel error={error} onRetry={reset} />
    </main>
  );
}
