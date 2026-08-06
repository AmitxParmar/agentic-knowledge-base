/**
 * features/research/components/ingestion-stage-timeline.tsx
 * ---------------------------------------------------------
 * Purpose:    4-stage ingestion timeline mapping the JobStage enum to
 *             pending/active/complete states.
 * Dependencies: stage-pill.tsx, ingestion-stage-timeline.module.css
 * Scope:      Upload progress display.
 */

import { StagePill } from "./stage-pill";
import styles from "./ingestion-stage-timeline.module.css";

const STAGES = [
  "Uploading document...",
  "Extracting content...",
  "Chunking content...",
  "Creating embeddings...",
];

interface IngestionStageTimelineProps {
  stage: string | null;
  error: string | null;
}

const STAGE_INDEX_MAP: Record<string, number> = {
  queued: -1,
  extracting: 1,
  chunking: 2,
  embedding: 3,
  done: 4,
  failed: -1,
};

export function IngestionStageTimeline({ stage, error }: IngestionStageTimelineProps) {
  const currentIndex = stage ? (STAGE_INDEX_MAP[stage] ?? -1) : -1;

  return (
    <div>
      <p className={styles.label}>Ingestion Progress</p>
      <div className={styles.timeline} role="log" aria-live="polite" aria-label="Ingestion progress">
        {STAGES.map((label, index) => {
          let status: "pending" | "active" | "complete" | "failed" = "pending";
          if (error || stage === "failed") status = "failed";
          else if (currentIndex >= index + 1) status = "complete";
          else if (currentIndex === index) status = "active";

          return <StagePill key={label} stage={label} status={status} />;
        })}
      </div>
    </div>
  );
}
