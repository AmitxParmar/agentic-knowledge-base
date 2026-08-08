/**
 * features/research/components/stage-pill.tsx
 * -------------------------------------------
 * Purpose:    Single progress stage indicator (pending/active/complete/failed).
 * Dependencies: stage-pill.module.css, lib/utils.ts
 * Scope:      Progress stage list.
 */

import { cn } from "@/lib/utils";
import styles from "./stage-pill.module.css";

type StageStatus = "pending" | "active" | "complete" | "failed";

interface StagePillProps {
  stage: string;
  status: StageStatus;
}

function StageIcon({ status }: { status: StageStatus }) {
  if (status === "complete") {
    return (
      <svg className={styles.icon} viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M3 8.5L6.5 12L13 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (status === "failed") {
    return (
      <svg className={styles.icon} viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M4 4L12 12M12 4L4 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg className={styles.icon} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="3" fill="currentColor" />
    </svg>
  );
}

export function StagePill({ stage, status }: StagePillProps) {
  return (
    <span className={cn(styles.pill, styles[status])}>
      <StageIcon status={status} />
      {stage.toUpperCase()}
    </span>
  );
}
