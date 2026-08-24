/**
 * features/research/components/task-rows.tsx
 * ------------------------------------------
 * Purpose:    Status rows for live/past agent work — status glyph, label,
 *             right-aligned meta. Ported from Beautiful UI "Task Rows",
 *             restyled to Tactical Telemetry tokens.
 * Dependencies: task-rows.module.css
 * Scope:      Runs page and any future task/status lists.
 */

"use client";

import styles from "./task-rows.module.css";

export type TaskRowStatus = "running" | "complete" | "failed" | "pending";

export interface TaskRow {
  id: string;
  label: string;
  meta?: string;
  status: TaskRowStatus;
}

const STATUS_GLYPH: Record<TaskRowStatus, string> = {
  running: "▶",
  complete: "✓",
  failed: "✕",
  pending: "·",
};

export function TaskRows({
  rows,
  onSelect,
}: {
  rows: TaskRow[];
  onSelect?: (id: string) => void;
}) {
  return (
    <ul className={styles.list}>
      {rows.map((row) => (
        <li key={row.id}>
          <button
            type="button"
            className={styles.row}
            onClick={onSelect ? () => onSelect(row.id) : undefined}
          >
            <span className={`${styles.status} ${styles[row.status]}`} aria-hidden="true">
              {STATUS_GLYPH[row.status]}
            </span>
            <span className="sr-only">{row.status}</span>
            <span className={styles.label}>{row.label}</span>
            {row.meta && <span className={styles.meta}>{row.meta}</span>}
          </button>
        </li>
      ))}
    </ul>
  );
}
