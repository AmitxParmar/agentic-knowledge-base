/**
 * features/research/components/upload-composer.tsx
 * -------------------------------------------------
 * Purpose:    Compact ingestion panel — source type + file picker + upload.
 *             Ingestion progress renders through the same ThinkingTrace used
 *             by the research chat, fed by job-status polling and mapped to
 *             the canonical ux.md ingestion stages.
 * Dependencies: api/use-upload.ts, api/use-job-status.ts, thinking-trace.tsx
 * Scope:      Research page ingestion panel.
 */

"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { cn } from "@/lib/utils";
import { useUpload } from "../api/use-upload";
import { useJobStatus } from "../api/use-job-status";
import { ThinkingTrace } from "./thinking-trace";

type SourceType = "pdf" | "repo" | "audio";

const SOURCE_TYPES: SourceType[] = ["pdf", "repo", "audio"];

/** Canonical ingestion stages (docs/ux.md). Order = pipeline order. */
const INGESTION_STAGES = [
  "Uploading document...",
  "Extracting content...",
  "Chunking content...",
  "Creating embeddings...",
];

const STAGE_INDEX_MAP: Record<string, number> = {
  queued: -1,
  extracting: 1,
  chunking: 2,
  embedding: 3,
  done: 4,
  failed: -1,
};

interface UploadComposerProps {
  onIngestionComplete?: (documentId: string) => void;
}

export function UploadComposer({ onIngestionComplete }: UploadComposerProps) {
  const [file, setFile] = useState<File | null>(null);
  const [sourceType, setSourceType] = useState<SourceType>("pdf");
  const [localError, setLocalError] = useState<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const upload = useUpload();
  const jobStatus = useJobStatus(activeJobId);

  const currentStage = jobStatus.data?.stage ?? null;
  const isTerminal = currentStage === "done" || currentStage === "failed";

  useEffect(() => {
    if (currentStage === "done" && jobStatus.data) {
      onIngestionComplete?.(jobStatus.data.document_id);
    }
  }, [currentStage, jobStatus.data, onIngestionComplete]);

  // Keep in sync with MAX_UPLOAD_SIZE / MAX_PDF_PAGES in apps/api/app/settings.py
  const MAX_UPLOAD_MB = 100;

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    setLocalError(null);

    if (selected) {
      // Size guard — fail fast before the round-trip
      if (selected.size > MAX_UPLOAD_MB * 1024 * 1024) {
        setLocalError(`File exceeds the ${MAX_UPLOAD_MB} MB limit.`);
        setFile(null);
        event.target.value = "";
        return;
      }
      // Type guard for PDF uploads
      if (
        sourceType === "pdf" &&
        selected.type !== "application/pdf" &&
        !selected.name.toLowerCase().endsWith(".pdf")
      ) {
        setLocalError("Only PDF files are supported for this source type.");
        setFile(null);
        event.target.value = "";
        return;
      }
    }

    setFile(selected);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setLocalError("Choose a file before uploading.");
      return;
    }

    setLocalError(null);
    setStartedAt(Date.now());
    try {
      const result = await upload.mutateAsync({ file, sourceType });
      setActiveJobId(result.job_id);
    } catch (err: unknown) {
      // Surface server's `detail` field when available; fall back to generic message
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err as Error)?.message ??
        "Upload failed. Please try again.";
      setLocalError(detail);
    }
  }

  const isUploading = upload.isPending || (activeJobId !== null && !isTerminal);

  // Map polled job state onto the canonical stage list for ThinkingTrace.
  const jobFailed = currentStage === "failed" || Boolean(jobStatus.data?.error);
  const currentIndex = currentStage ? (STAGE_INDEX_MAP[currentStage] ?? -1) : -1;
  const traceActive = upload.isPending || (activeJobId !== null && !isTerminal && !jobFailed);
  const reachedCount =
    currentIndex < 0 ? 1 : Math.min(currentIndex + 1, INGESTION_STAGES.length);
  const traceStages = jobFailed ? INGESTION_STAGES.slice(0, Math.max(1, reachedCount)) : INGESTION_STAGES.slice(0, reachedCount);

  return (
    <form
      onSubmit={handleSubmit}
      className="mx-auto w-full max-w-[760px] rounded-card border border-line bg-surface p-4 shadow-card"
    >
      {/* controls row */}
      {!activeJobId && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-medium text-ink">Ingest a document</span>
            <div role="radiogroup" aria-label="Source type" className="ml-auto flex gap-0.5 rounded-chip bg-inset p-0.5">
              {SOURCE_TYPES.map((type) => (
                <button
                  key={type}
                  type="button"
                  role="radio"
                  aria-checked={sourceType === type}
                  className={cn(
                    "h-6.5 rounded-[7px] px-2.5 text-[11.5px] font-medium uppercase tracking-wide transition-colors duration-150",
                    sourceType === type ? "bg-surface-raised text-ink shadow-btn" : "text-ink-3 hover:text-ink",
                  )}
                  onClick={() => setSourceType(type)}
                >
                  {type}
                </button>
              ))}
            </div>
          </div>

          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex min-h-16 items-center justify-center gap-2 rounded-control border border-dashed border-line-strong bg-inset px-3 py-3 text-[12.5px] text-ink-3 transition-colors duration-150 hover:border-accent hover:bg-accent-tint hover:text-ink"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="m21.4 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
            </svg>
            {file ? file.name : `Choose a ${sourceType.toUpperCase()} or drag it here`}
            {file && (
              <span className="text-ink-3 tabular-nums">· {(file.size / 1024).toFixed(1)} KB</span>
            )}
          </button>
          <input
            ref={fileInputRef}
            id="file-input"
            type="file"
            onChange={handleFileChange}
            className="sr-only"
            aria-label="Choose a file to ingest"
          />

          <div className="flex items-center gap-2">
            <button
              type="submit"
              disabled={!file || isUploading}
              className={cn(
                "ml-auto flex h-8.5 items-center gap-1.5 rounded-control px-3.5 text-[12.5px] font-medium transition-[background-color,color,transform] duration-200",
                file && !isUploading
                  ? "bg-ink text-page enabled:active:scale-[0.97]"
                  : "cursor-not-allowed bg-line-strong text-ink-2 opacity-60",
              )}
            >
              {isUploading ? "Uploading…" : "Start ingestion"}
            </button>
          </div>
        </div>
      )}

      {localError && (
        <p className="mt-2 text-right text-[12px] text-red" role="alert">
          {localError}
        </p>
      )}
      {jobStatus.data?.error && (
        <p className="mt-2 text-right text-[12px] text-red" role="alert">
          {jobStatus.data.error}
        </p>
      )}

      {(activeJobId || upload.isPending) && (
        <ThinkingTrace
          stages={traceStages}
          status={jobFailed ? "error" : traceActive ? "running" : "complete"}
          startedAt={startedAt}
          label="Ingesting"
          error={jobStatus.data?.error ?? null}
        />
      )}
    </form>
  );
}
