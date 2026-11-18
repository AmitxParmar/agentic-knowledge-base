/**
 * features/devicehub/components/dashboard-state.tsx
 * -------------------------------------------------
 * Purpose:    Shared loading / error / empty states. The error state knows
 *             the difference between "hub is cold starting" and "your token
 *             is wrong", because a free-tier Render service sleeps.
 * Dependencies: api/client.ts, dashboard-state.module.css
 * Scope:      Dashboard views.
 */

"use client";

import styles from "./dashboard-state.module.css";
import { describeFailure } from "@/features/devicehub/api/client";

export function LoadingPanel({ label }: { label: string }) {
  return (
    <div className={styles.panel} role="status" aria-live="polite">
      <span className={styles.spinner} aria-hidden="true" />
      <div>
        <p className={styles.title}>{label}</p>
        <p className={styles.detail}>
          A free-tier hub can take up to a minute to wake up.
        </p>
      </div>
    </div>
  );
}

export function ErrorPanel({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const { title, detail, retryable } = describeFailure(error);

  return (
    <div className={styles.panel} role="alert">
      <div>
        <p className={styles.title}>{title}</p>
        <p className={styles.detail}>{detail}</p>
      </div>
      {retryable && onRetry ? (
        <button type="button" className={styles.retry} onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function EmptyPanel({
  title,
  detail,
  children,
}: {
  title: string;
  detail: string;
  children?: React.ReactNode;
}) {
  return (
    <div className={styles.empty}>
      <p className={styles.title}>{title}</p>
      <p className={styles.detail}>{detail}</p>
      {children}
    </div>
  );
}
