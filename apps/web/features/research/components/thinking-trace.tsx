/**
 * features/research/components/thinking-trace.tsx
 * ------------------------------------------------
 * Purpose:    Perplexity-style inline agent trace for an in-flight research
 *             run. While the run streams, the trace is expanded and shows
 *             each canonical progress stage (docs/ux.md vocabulary only) as
 *             spinner → muted check. Once settled it collapses to a summary
 *             header that stays expandable.
 *
 *             Compliance: renders ONLY the stage strings emitted by the
 *             backend — no reasoning, no tool payloads (docs/ux.md).
 * Dependencies: none (pure presentational; state comes from useResearchRun)
 * Scope:      Research chat answer area + ingestion panel.
 */

"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export type TraceStatus = "running" | "complete" | "error";

interface ThinkingTraceProps {
  /** Canonical stage labels already reached, in pipeline order. */
  stages: string[];
  status: TraceStatus;
  /** Epoch ms when the run started — drives the settled elapsed readout. */
  startedAt?: number | null;
  /** Settled summary meta, e.g. citation count. */
  sourcesCount?: number;
  /** Error message rendered under the last row on failure. */
  error?: string | null;
  /** Header noun for contexts other than research ("Ingesting"). */
  label?: string;
  /** Override the auto-expand rule (default: expanded while running). */
  autoExpanded?: boolean;
}

/** Past-tense stem of a ux.md stage string: "Searching documents..." → "Searching documents". */
function stem(stage: string): string {
  return stage.replace(/\.\.\.$/, "");
}

function SpinnerRing() {
  return (
    <span
      aria-hidden="true"
      className="size-3 shrink-0 rounded-full border-[1.5px] border-line-strong border-t-ink-2"
      style={{ animation: "spin 700ms linear infinite" }}
    />
  );
}

function CheckIcon({ muted }: { muted?: boolean }) {
  return (
    <svg
      aria-hidden="true"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke={muted ? "var(--ink-3)" : "var(--ink-2)"}
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0"
    >
      <path d="M20 6L9 17l-5-5" />
    </svg>
  );
}

function FailIcon() {
  return (
    <svg
      aria-hidden="true"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--red)"
      strokeWidth="2.2"
      strokeLinecap="round"
      className="shrink-0"
    >
      <path d="M4 4l12 12M16 4L4 16" />
    </svg>
  );
}

export function ThinkingTrace({
  stages,
  status,
  startedAt,
  sourcesCount,
  error,
  label = "Researching",
  autoExpanded,
}: ThinkingTraceProps) {
  const working = status === "running";
  const failed = status === "error";
  const activeIdx = stages.length - 1;

  // Reference state machine: auto-expanded while working; the first manual
  // toggle takes over and persists.
  const [manualExpanded, setManualExpanded] = useState<boolean | null>(null);
  const auto = autoExpanded ?? working;
  const expanded = manualExpanded ?? auto;

  const [elapsed, setElapsed] = useState<number | null>(null);
  const traceRef = useRef<HTMLDivElement>(null);
  const [lineHeight, setLineHeight] = useState(0);

  // Capture settle time once so the summary stays stable after completion.
  useEffect(() => {
    if (working || !startedAt || elapsed !== null) return;
    setElapsed(Math.max(1, Math.round((Date.now() - startedAt) / 1000)));
  }, [working, startedAt, elapsed]);

  // Guide line grows with content.
  useLayoutEffect(() => {
    if (traceRef.current) setLineHeight(traceRef.current.offsetHeight);
  }, [stages.length, expanded, status]);

  if (stages.length === 0 && !working && !failed) return null;

  const activeStage = stages[activeIdx];
  const headerLabel = working
    ? activeStage
      ? stem(activeStage)
      : label
    : failed
      ? `${label} failed`
      : `${label} · ${elapsed ?? "?"}s`;

  return (
    <div className="flex w-full flex-col" data-testid="thinking-trace">
      {/* header */}
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setManualExpanded((current) => !(current ?? working))}
        className="-mx-1.5 flex w-fit items-center gap-2 rounded-control px-1.5 py-1 transition-colors duration-150 hover:bg-hover-2 min-h-11"
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill={working || failed ? "var(--ink-2)" : "var(--ink-3)"} aria-hidden="true">
          <path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z" />
        </svg>

        <span role="status" className="contents">
          {working ? (
            <span
              className="whitespace-nowrap bg-clip-text text-[13px] font-medium text-transparent"
              style={{
                backgroundImage:
                  "linear-gradient(90deg, var(--ink-3) 35%, var(--ink) 50%, var(--ink-3) 65%)",
                backgroundSize: "200% 100%",
                animation: "shimmer-text 1.4s linear infinite",
              }}
            >
              {headerLabel}
            </span>
          ) : (
            <span
              className={cn("whitespace-nowrap text-[13px] font-medium", failed ? "text-red" : "text-ink-2")}
              style={{ animation: "fade-in 300ms ease-out both" }}
            >
              {headerLabel}
            </span>
          )}
        </span>

        {status === "complete" && typeof sourcesCount === "number" && sourcesCount > 0 && (
          <span className="text-[12px] text-ink-3 tabular-nums">· {sourcesCount} sources</span>
        )}

        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--ink-3)"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="transition-transform duration-300"
          style={{ transform: expanded ? "rotate(180deg)" : "rotate(0deg)" }}
          aria-hidden="true"
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {/* expandable trace */}
      <div
        className="grid transition-[grid-template-rows,opacity] duration-300"
        style={{
          gridTemplateRows: expanded ? "1fr" : "0fr",
          opacity: expanded ? 1 : 0,
          transitionTimingFunction: "var(--ease-out-expo)",
        }}
      >
        <div className="overflow-hidden">
          <div className="relative mt-1 ml-[5px] pl-4">
            <span
              aria-hidden="true"
              className="absolute left-[3px] w-px bg-line"
              style={{
                top: -6,
                height: lineHeight ? lineHeight - 2 : 0,
                transition: "height 400ms var(--ease-out-expo)",
              }}
            />
            <div ref={traceRef} className="flex flex-col gap-1 py-1">
              {stages.map((stage, i) => {
                const isActive = working && i === activeIdx;
                return (
                  <div
                    key={stage}
                    className="flex min-h-6 w-full items-center gap-2 px-1 text-left"
                    style={{ animation: `fade-up 320ms var(--ease-out-expo) ${Math.min(i, 4) * 90}ms both` }}
                  >
                    {isActive ? (
                      <SpinnerRing />
                    ) : failed && i === activeIdx ? (
                      <FailIcon />
                    ) : (
                      <CheckIcon muted={!working} />
                    )}
                    <span className="min-w-0 truncate text-[12.5px] font-medium text-ink">{stem(stage)}</span>
                  </div>
                );
              })}

              {failed && error && (
                <p className="px-1 pt-1 text-[12px] leading-relaxed text-red" role="alert">
                  {error}
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
