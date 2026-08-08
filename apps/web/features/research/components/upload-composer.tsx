/**
 * features/research/components/upload-composer.tsx
 * -----------------------------------------------
 * Purpose:    Compound upload component — file picker + source-type select
 *             + upload CTA + stage timeline.
 * Dependencies: upload-composer.module.css, stage-pill.tsx, progress-stage-list.tsx
 * Scope:      Research page upload section.
 */

"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useUpload } from "../api/use-upload";
import { useJobStatus } from "../api/use-job-status";
import { IngestionStageTimeline } from "./ingestion-stage-timeline";
import styles from "./upload-composer.module.css";

type SourceType = "pdf" | "repo" | "audio";

const SOURCE_TYPES: SourceType[] = ["pdf", "repo", "audio"];

interface UploadComposerProps {
  onIngestionComplete?: (documentId: string) => void;
}

export function UploadComposer({ onIngestionComplete }: UploadComposerProps) {
  const [file, setFile] = useState<File | null>(null);
  const [sourceType, setSourceType] = useState<SourceType>("pdf");
  const [localError, setLocalError] = useState<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  const upload = useUpload();
  const jobStatus = useJobStatus(activeJobId);

  const currentStage = jobStatus.data?.stage ?? null;
  const isTerminal = currentStage === "done" || currentStage === "failed";

  useEffect(() => {
    if (currentStage === "done" && jobStatus.data) {
      onIngestionComplete?.(jobStatus.data.document_id);
    }
  }, [currentStage, jobStatus.data, onIngestionComplete]);

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
    setLocalError(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setLocalError("Choose a file before uploading.");
      return;
    }

    setLocalError(null);
    const result = await upload.mutateAsync({ file, sourceType });
    setActiveJobId(result.job_id);
  }

  const isUploading = upload.isPending || (activeJobId !== null && !isTerminal);

  return (
    <form className={styles.composer} onSubmit={handleSubmit}>
      <div className={styles.header}>
        <h2 className={styles.title}>1. Upload Source</h2>
        <span className={styles.badge}>{sourceType}</span>
      </div>

      <div className={styles.field}>
        <span className={styles.label} id="source-type-label">Source type</span>
        <div className={styles.segmented} role="radiogroup" aria-labelledby="source-type-label">
          {SOURCE_TYPES.map((type) => (
            <button
              key={type}
              type="button"
              role="radio"
              aria-checked={sourceType === type}
              className={`${styles.segment} ${sourceType === type ? styles.segmentActive : ""}`}
              onClick={() => setSourceType(type)}
            >
              {type.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      <div className={styles.field}>
        <span className={styles.label} id="file-label">File</span>
        <label className={styles.dropzone} htmlFor="file-input">
          <span className={styles.dropzoneText}>
            {file ? file.name : "Choose a file or drag it here"}
          </span>
        </label>
        <input
          id="file-input"
          type="file"
          onChange={handleFileChange}
          className="sr-only"
          aria-labelledby="file-label"
        />
      </div>

      {file && (
        <div className={styles.fileMeta}>
          <span className={styles.fileName}>{file.name}</span>
          <span className={styles.fileSize}>{(file.size / 1024).toFixed(1)} KB</span>
        </div>
      )}

      {activeJobId && (
        <IngestionStageTimeline stage={currentStage} error={jobStatus.data?.error ?? null} />
      )}

      <button
        type="submit"
        className={styles.submit}
        disabled={!file || isUploading}
      >
        {isUploading ? "Uploading..." : "Start ingestion"}
      </button>

      {localError && <p className={styles.error}>{localError}</p>}
      {jobStatus.data?.error && <p className={styles.error}>{jobStatus.data.error}</p>}
    </form>
  );
}
