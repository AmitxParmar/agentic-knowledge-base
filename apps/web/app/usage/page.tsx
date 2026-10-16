/**
 * app/usage/page.tsx
 * -------------------
 * Purpose:    Usage dashboard — today's + this month's token spend against
 *             the daily budget, with an over-budget warning state.
 * Dependencies: api/use-usage.ts, usage.module.css
 * Scope:      Read-only display; budgets are set server-side.
 */

"use client";

import { useUsage } from "@/features/research/api/use-usage";
import styles from "./usage.module.css";

function formatTokens(n: number): string {
  // Step 1: render compact thousands (12.4k) for readability.
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return `${n}`;
}

export default function UsagePage() {
  // Step 1: load the spend snapshot (today + month + effective budget).
  const { data, isLoading, error } = useUsage();

  if (isLoading) return <p className={styles.empty}>Loading usage…</p>;
  if (error)
    return (
      <p className={styles.error} role="alert">
        Failed to load usage.
      </p>
    );
  if (!data) return null;

  // Step 2: derive the budget bar state (null budget = unlimited).
  const pct = data.pct_used === null ? 0 : Math.min(data.pct_used, 1);
  const barState = data.over_budget ? styles.over : data.pct_used !== null && data.pct_used >= 0.8 ? styles.warn : "";

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>Usage</h1>
      <p className={styles.subtitle}>LLM token spend across your research runs.</p>

      {data.over_budget && (
        <p className={styles.alert} role="alert">
          Daily budget exhausted — new runs are refused until tomorrow.
        </p>
      )}

      <div className={styles.cards}>
        <div className={styles.card}>
          <h2 className={styles.cardLabel}>Today</h2>
          <p className={styles.cardValue}>{formatTokens(data.today_tokens)}</p>
          <p className={styles.cardMeta}>tokens</p>
        </div>
        <div className={styles.card}>
          <h2 className={styles.cardLabel}>This month</h2>
          <p className={styles.cardValue}>{formatTokens(data.month_tokens)}</p>
          <p className={styles.cardMeta}>tokens</p>
        </div>
        <div className={styles.card}>
          <h2 className={styles.cardLabel}>Daily budget</h2>
          <p className={styles.cardValue}>
            {data.daily_budget === null ? "∞" : formatTokens(data.daily_budget)}
          </p>
          <p className={styles.cardMeta}>{data.daily_budget === null ? "unlimited" : "tokens / day"}</p>
        </div>
      </div>

      {data.daily_budget !== null && (
        <div className={styles.budgetSection}>
          <div className={styles.budgetRow}>
            <span>Budget used</span>
            <span>{Math.round((data.pct_used ?? 0) * 100)}%</span>
          </div>
          <div className={styles.budgetBar} role="progressbar" aria-valuenow={Math.round(pct * 100)} aria-valuemin={0} aria-valuemax={100}>
            <div className={`${styles.budgetFill} ${barState}`} style={{ width: `${pct * 100}%` }} />
          </div>
        </div>
      )}
    </div>
  );
}
