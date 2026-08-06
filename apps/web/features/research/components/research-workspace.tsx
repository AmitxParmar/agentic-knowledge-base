/**
 * features/research/components/research-workspace.tsx
 * ---------------------------------------------------
 * Purpose:    Orchestrates the full research loop — upload → ask → answer.
 *             Uses TanStack AI's ResearchChat (ws-transport adapter) for the
 *             question/chat flow, and the AnswerPanel for the final result.
 * Dependencies: upload-composer, research-chat, answer-panel
 * Scope:      /research page body.
 */

"use client";

import { useState } from "react";
import { UploadComposer } from "./upload-composer";
import { ResearchChat } from "./research-chat";
import { AnswerPanel } from "./answer-panel";
import { ProgressStageList } from "./progress-stage-list";
import { useResearchRun } from "../api/use-research-run";
import styles from "./research-workspace.module.css";

export function ResearchWorkspace() {
  const [ready, setReady] = useState(false);
  const { state, startResearch } = useResearchRun();

  return (
    <main className={styles.workspace}>
      <UploadComposer onIngestionComplete={() => setReady(true)} />

      <ResearchChat
        disabled={!ready}
        onQuestion={startResearch}
      />

      {state.stages.length > 0 && (
        <div className={styles.progressSection}>
          <ProgressStageList
            completedStages={state.stages.slice(0, -1)}
            currentStage={state.stages[state.stages.length - 1] ?? null}
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
