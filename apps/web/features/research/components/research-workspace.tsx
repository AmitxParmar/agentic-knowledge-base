/**
 * features/research/components/research-workspace.tsx
 * ---------------------------------------------------
 * Purpose:    Orchestrates the full research loop — upload → poll → ask →
 *             progress → answer — within a single client component.
 * Dependencies: upload-composer, question-composer, progress-stage-list,
 *               answer-panel, use-research-run
 * Scope:      /research page body.
 */

"use client";

import { useState } from "react";
import { UploadComposer } from "./upload-composer";
import { QuestionComposer } from "./question-composer";
import { ProgressStageList } from "./progress-stage-list";
import { AnswerPanel } from "./answer-panel";
import { useResearchRun } from "../api/use-research-run";
import styles from "./research-workspace.module.css";

export function ResearchWorkspace() {
  const [ready, setReady] = useState(false);
  const { state, startResearch } = useResearchRun();

  const currentStage = state.stages[state.stages.length - 1] ?? null;

  return (
    <main className={styles.workspace}>
      <UploadComposer onIngestionComplete={() => setReady(true)} />

      <QuestionComposer disabled={!ready} onSubmit={startResearch} />

      {state.stages.length > 0 && (
        <div className={styles.progressSection}>
          <ProgressStageList
            completedStages={state.stages.slice(0, -1)}
            currentStage={currentStage}
          />
        </div>
      )}

      {state.error && (
        <p className={styles.error} role="alert">
          {state.error}
        </p>
      )}

      <AnswerPanel answer={state.answer} citations={state.citations} />
    </main>
  );
}
