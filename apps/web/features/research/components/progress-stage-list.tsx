/**
 * features/research/components/progress-stage-list.tsx
 * ----------------------------------------------------
 * Purpose:    Fixed-vocabulary stage timeline. Renders research stages as
 *             pending/active/complete — the only progress vocabulary allowed
 *             on the client (docs/ux.md).
 * Dependencies: stage-pill.tsx, progress-stage-list.module.css
 * Scope:      Research run progress display.
 */

import { StagePill } from "./stage-pill";
import styles from "./progress-stage-list.module.css";

type StageStatus = "pending" | "active" | "complete";

interface ProgressStageListProps {
  stages: Array<{ stage: string; status: StageStatus }>;
}

export function ProgressStageList({ stages }: ProgressStageListProps) {
  return (
    <div>
      <p className={styles.label}>PROGRESS</p>
      <div className={styles.list} role="log" aria-live="polite" aria-label="Research progress">
        {stages.map((s) => (
          <StagePill key={s.stage} stage={s.stage} status={s.status} />
        ))}
      </div>
    </div>
  );
}
