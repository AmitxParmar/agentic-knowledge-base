/**
 * features/research/components/cold-start-splash.tsx
 * --------------------------------------------------
 * Purpose:    Full-viewport splash shown while the server boots (Render cold
 *             start, dev restart, downtime). Renders time-based stage pills
 *             using the existing StagePill component. Polls /health until
 *             reachable, then fades out and reveals the workspace.
 * Dependencies: use-server-readiness.ts, stage-pill.tsx, cold-start-splash.module.css
 * Scope:      Cold-start gate for the research page.
 */

"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { useServerReadiness } from "../api/use-server-readiness";
import { StagePill } from "./stage-pill";
import styles from "./cold-start-splash.module.css";

interface ColdStartSplashProps {
  onReady: () => void;
}

export function ColdStartSplash({ onReady }: ColdStartSplashProps) {
  const { stages, status, attempt, ready } = useServerReadiness();
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    if (!ready) return;

    const timeout = setTimeout(() => {
      setExiting(true);
      setTimeout(onReady, 200);
    }, 600);

    return () => clearTimeout(timeout);
  }, [ready, onReady]);

  const handleSkip = () => {
    setExiting(true);
    setTimeout(onReady, 200);
  };

  return (
    <div
      className={cn(styles.splash, exiting && styles.exiting)}
      role="status"
      aria-live="polite"
      aria-label="Server is starting"
    >
      <div className={styles.content}>
        <h1 className={styles.title}>Agentic Research Workspace</h1>
        <p className={styles.subtitle}>
          {status === "ready"
            ? "Server connected. Loading workspace…"
            : "Waiting for the server to be ready. This may take a moment on first visit."}
        </p>

        <div className={styles.stages} role="list">
          {stages.map((stage) => (
            <StagePill key={stage.label} stage={stage.label} status={stage.status} />
          ))}
        </div>

        <button
          type="button"
          className={styles.skipButton}
          onClick={handleSkip}
          aria-label="Skip waiting and continue to workspace"
        >
          Skip →
        </button>

        {attempt > 1 && status !== "ready" && (
          <p className={styles.attempt}>
            Retrying… attempt {attempt}
          </p>
        )}
      </div>
    </div>
  );
}
