/**
 * features/research/components/progress-stage-list.tsx
 * ----------------------------------------------------
 * Purpose:    Fixed-vocabulary stage timeline. Maps the 4 research stages
 *             (from docs/ux.md) to pending/active/complete states.
 * Dependencies: stage-pill.tsx, progress-stage-list.module.css
 * Scope:      Research run progress display.
 */

import { StagePill } from "./stage-pill";
import styles from "./progress-stage-list.module.css";

const STAGES = [
  "Searching documents...",
  "Reviewing evidence...",
  "Generating report...",
  "Finalizing answer...",
];

interface ProgressStageListProps {
  completedStages: string[];
  currentStage: string | null;
}

export function ProgressStageList({ completedStages, currentStage }: ProgressStageListProps) {
  return (
    <div>
      <p className={styles.label}>Progress</p>
      <div className={styles.list} role="log" aria-live="polite" aria-label="Research progress">
        {STAGES.map((stage) => {
          const isComplete = completedStages.includes(stage);
          const isCurrent = stage === currentStage;

          let status: "pending" | "active" | "complete" = "pending";
          if (isComplete) status = "complete";
          else if (isCurrent) status = "active";

          return <StagePill key={stage} stage={stage} status={status} />;
        })}
      </div>
    </div>
  );
}
