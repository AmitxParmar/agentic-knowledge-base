/**
 * app/runs/page.tsx
 * -----------------
 * Purpose:    Runs route — lists past research runs, click to view detail.
 * Dependencies: api/use-run-history.ts, runs.module.css
 * Scope:      Phase 2 runs data.
 */

"use client";

import { useState } from "react";
import { useRunHistory } from "@/features/research/api/use-run-history";
import { useRunDetail } from "@/features/research/api/use-research-run";
import { TaskRows, type TaskRowStatus } from "@/features/research/components/task-rows";
import styles from "./runs.module.css";

function toTaskRowStatus(status: string): TaskRowStatus {
  // ponytail: pass-through for known statuses, anything else renders as pending
  if (status === "running" || status === "complete" || status === "failed") return status;
  return "pending";
}

function RunDetail({ runId, onBack }: { runId: string; onBack: () => void }) {
  const { data, isLoading, error } = useRunDetail(runId);

  if (isLoading) return <p className={styles.empty}>Loading run…</p>;
  if (error) return <p className={styles.error} role="alert">Failed to load run.</p>;
  if (!data) return null;

  return (
    <div className={styles.container}>
      <button type="button" className={styles.backButton} onClick={onBack}>
        ← Back to runs
      </button>
      <h1 className={styles.title}>Run Detail</h1>
      <p className={styles.question}>{data.question}</p>
      <span className={`${styles.badge} ${styles[data.status] ?? ""}`}>{data.status}</span>

      <div className={styles.answerSection}>
        <h2 className={styles.sectionLabel}>Answer</h2>
        <p className={styles.answer}>{data.answer ?? "No answer recorded."}</p>
      </div>

      {data.citations.length > 0 && (
        <div className={styles.citationSection}>
          <h2 className={styles.sectionLabel}>Citations</h2>
          <ul className={styles.citationList}>
            {data.citations.map((c) => (
              <li key={c.chunk_id} className={styles.citationItem}>
                <code className={styles.citationId}>{c.chunk_id}</code>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function RunList({ onSelect }: { onSelect: (runId: string) => void }) {
  const { data, isLoading, error } = useRunHistory();

  if (isLoading) return <p className={styles.empty}>Loading runs…</p>;
  if (error) return <p className={styles.error} role="alert">Failed to load runs.</p>;
  if (!data || data.runs.length === 0) {
    return (
      <div className={styles.container}>
        <h1 className={styles.title}>Run History</h1>
        <p className={styles.empty}>No research runs yet.</p>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>Run History</h1>
      <p className={styles.subtitle}>
        {data.total} run{data.total === 1 ? "" : "s"}
      </p>

      <TaskRows
        rows={data.runs.map((run) => ({
          id: run.run_id,
          label: run.question,
          meta: new Date(run.created_at).toLocaleDateString(),
          status: toTaskRowStatus(run.status),
        }))}
        onSelect={onSelect}
      />
    </div>
  );
}

export default function RunsPage() {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  if (selectedRunId) {
    return <RunDetail runId={selectedRunId} onBack={() => setSelectedRunId(null)} />;
  }

  return <RunList onSelect={setSelectedRunId} />;
}
