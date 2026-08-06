/**
 * features/research/api/use-server-readiness.ts
 * ------------------------------------------------
 * Purpose:    Poll /health until the server is reachable (handles Render
 *             cold start, local dev restarts, any downtime). Tracks elapsed
 *             time and derives staged status messages for the boot splash.
 * Dependencies: lib/env.ts
 * Scope:      Cold-start splash data source.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "@/lib/env";

export type ReadinessStatus = "connecting" | "starting" | "warming" | "almost" | "ready";

export interface ReadinessState {
  status: ReadinessStatus;
  stages: Array<{ label: string; status: "pending" | "active" | "complete" }>;
  attempt: number;
  elapsedMs: number;
  ready: boolean;
}

const STAGES = [
  { threshold: 0, key: "connecting", label: "Connecting to server..." },
  { threshold: 5000, key: "starting", label: "Server is starting (cold start)..." },
  { threshold: 15000, key: "warming", label: "Warming up AI agent..." },
  { threshold: 30000, key: "almost", label: "Almost ready..." },
];

const POLL_INTERVAL_MS = 2000;
const REQUEST_TIMEOUT_MS = 5000;

function deriveStages(elapsedMs: number): ReadinessState["stages"] {
  const activeIndex = STAGES.reduce((acc, stage, idx) => {
    return elapsedMs >= stage.threshold ? idx : acc;
  }, 0);

  return STAGES.map((stage, idx) => ({
    label: stage.label,
    status: idx < activeIndex ? "complete" : idx === activeIndex ? "active" : "pending",
  }));
}

function deriveStatus(elapsedMs: number): ReadinessStatus {
  if (elapsedMs >= 30000) return "almost";
  if (elapsedMs >= 15000) return "warming";
  if (elapsedMs >= 5000) return "starting";
  return "connecting";
}

async function checkHealth(signal: AbortSignal): Promise<boolean> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(`${API_BASE_URL}/health`, {
      method: "GET",
      signal: controller.signal,
      cache: "no-store",
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
    signal.removeEventListener("abort", onAbort);
  }

  function onAbort() {
    controller.abort();
  }
}

export function useServerReadiness(): ReadinessState & { skip: () => void } {
  const [state, setState] = useState<ReadinessState>({
    status: "connecting",
    stages: deriveStages(0),
    attempt: 0,
    elapsedMs: 0,
    ready: false,
  });
  const startTimeRef = useRef(Date.now());
  const attemptRef = useRef(0);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const skip = useCallback(() => {
    setState((prev) => ({
      ...prev,
      status: "ready",
      stages: prev.stages.map((s) => ({ ...s, status: "complete" as const })),
      ready: true,
    }));
    if (pollRef.current) clearTimeout(pollRef.current);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      attemptRef.current += 1;
      const attempt = attemptRef.current;
      const elapsedMs = Date.now() - startTimeRef.current;

      const healthy = await checkHealth(new AbortController().signal);

      if (cancelled) return;

      if (healthy) {
        setState({
          status: "ready",
          stages: deriveStages(elapsedMs).map((s) => ({ ...s, status: "complete" as const })),
          attempt,
          elapsedMs,
          ready: true,
        });
        return;
      }

      setState({
        status: deriveStatus(elapsedMs),
        stages: deriveStages(elapsedMs),
        attempt,
        elapsedMs,
        ready: false,
      });

      pollRef.current = setTimeout(poll, POLL_INTERVAL_MS);
    }

    pollRef.current = setTimeout(poll, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, []);

  return { ...state, skip };
}
