"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import styles from "./page.module.css";

type SourceType = "pdf" | "repo" | "audio";

type UploadState = {
  documentId: string | null;
  jobId: string | null;
  stage: string | null;
  error: string | null;
};

type Citation = {
  chunk_id: string;
  source_ref: string;
  relevance_score: number;
};

type AnswerState = {
  text: string;
  citations: Citation[];
  stages: string[];
  error: string | null;
};

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const WS_BASE_URL = API_BASE_URL.replace(/^http/, "ws");

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [sourceType, setSourceType] = useState<SourceType>("pdf");
  const [question, setQuestion] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [isAsking, setIsAsking] = useState(false);
  const [uploadState, setUploadState] = useState<UploadState>({
    documentId: null,
    jobId: null,
    stage: null,
    error: null,
  });
  const [answerState, setAnswerState] = useState<AnswerState>({
    text: "",
    citations: [],
    stages: [],
    error: null,
  });
  const pollTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) {
        window.clearTimeout(pollTimerRef.current);
      }
    };
  }, []);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setUploadState((current) => ({
        ...current,
        error: "Choose a file before uploading.",
      }));
      return;
    }

    setIsUploading(true);
    setUploadState({
      documentId: null,
      jobId: null,
      stage: null,
      error: null,
    });

    const formData = new FormData();
    formData.append("file", file);
    formData.append("source_type", sourceType);

    try {
      const response = await fetch(`${API_BASE_URL}/api/ingestion/upload`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        throw new Error(`Upload failed with status ${response.status}`);
      }

      const data = (await response.json()) as {
        document_id: string;
        job_id: string;
        status: string;
      };

      setUploadState({
        documentId: data.document_id,
        jobId: data.job_id,
        stage: data.status,
        error: null,
      });
      void pollJob(data.job_id);
    } catch (error) {
      setUploadState({
        documentId: null,
        jobId: null,
        stage: null,
        error: error instanceof Error ? error.message : "Upload failed.",
      });
    } finally {
      setIsUploading(false);
    }
  }

  async function pollJob(jobId: string) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/ingestion/jobs/${jobId}`);
      if (!response.ok) {
        throw new Error(`Status check failed with status ${response.status}`);
      }

      const data = (await response.json()) as {
        stage: string;
        error: string | null;
      };

      setUploadState((current) => ({
        ...current,
        stage: data.stage,
        error: data.error,
      }));

      if (data.stage === "done" || data.stage === "failed") {
        return;
      }

      pollTimerRef.current = window.setTimeout(() => {
        void pollJob(jobId);
      }, 1200);
    } catch (error) {
      setUploadState((current) => ({
        ...current,
        error: error instanceof Error ? error.message : "Status check failed.",
      }));
    }
  }

  async function handleAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim()) {
      setAnswerState((current) => ({
        ...current,
        error: "Enter a question before asking.",
      }));
      return;
    }

    setIsAsking(true);
    setAnswerState({
      text: "",
      citations: [],
      stages: [],
      error: null,
    });

    const ws = new WebSocket(`${WS_BASE_URL}/api/research/ws`);

    ws.onopen = () => {
      ws.send(JSON.stringify({ question: question.trim() }));
    };

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data) as
        | { type: "progress"; stage: string }
        | { type: "answer"; text: string; citations: Citation[] }
        | { type: "error"; message: string }
        | { type: "done" };

      if (message.type === "progress") {
        setAnswerState((current) => ({
          ...current,
          stages: [...current.stages, message.stage],
        }));
      }

      if (message.type === "answer") {
        setAnswerState((current) => ({
          ...current,
          text: message.text,
          citations: message.citations,
        }));
      }

      if (message.type === "error") {
        setAnswerState((current) => ({
          ...current,
          error: message.message,
        }));
        setIsAsking(false);
      }

      if (message.type === "done") {
        setIsAsking(false);
        ws.close();
      }
    };

    ws.onerror = () => {
      setAnswerState((current) => ({
        ...current,
        error: "WebSocket connection failed.",
      }));
      setIsAsking(false);
    };
  }

  const canAsk = uploadState.stage === "done" && !isAsking;

  return (
    <main className={styles.shell}>
      <section className={styles.hero}>
        <p className={styles.eyebrow}>Agentic Research Workspace</p>
        <h1 className={styles.title}>Upload. Ask. Get a cited answer.</h1>
        <p className={styles.subtitle}>
          This page is the thinnest possible core-flow harness for the MVP:
          ingestion status, research progress, and citation output in one place.
        </p>
      </section>

      <section className={styles.grid}>
        <form className={styles.card} onSubmit={handleUpload}>
          <div className={styles.cardHeader}>
            <h2>1. Upload Source</h2>
            <span className={styles.badge}>{sourceType}</span>
          </div>

          <label className={styles.label}>
            Source type
            <select
              className={styles.select}
              value={sourceType}
              onChange={(event) => setSourceType(event.target.value as SourceType)}
            >
              <option value="pdf">PDF</option>
              <option value="repo">Repo</option>
              <option value="audio">Audio</option>
            </select>
          </label>

          <label className={styles.label}>
            File
            <input
              className={styles.input}
              type="file"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>

          <button className={styles.primaryButton} disabled={isUploading}>
            {isUploading ? "Uploading..." : "Start ingestion"}
          </button>

          <dl className={styles.metaList}>
            <div>
              <dt>Document</dt>
              <dd>{uploadState.documentId ?? "Not uploaded yet"}</dd>
            </div>
            <div>
              <dt>Job</dt>
              <dd>{uploadState.jobId ?? "Waiting"}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{uploadState.stage ?? "Idle"}</dd>
            </div>
          </dl>

          {uploadState.error ? (
            <p className={styles.errorText}>{uploadState.error}</p>
          ) : null}
        </form>

        <form className={styles.card} onSubmit={handleAsk}>
          <div className={styles.cardHeader}>
            <h2>2. Ask A Question</h2>
            <span className={styles.badge}>{canAsk ? "ready" : "waiting"}</span>
          </div>

          <label className={styles.label}>
            Question
            <textarea
              className={styles.textarea}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="What does this document say about...?"
            />
          </label>

          <button className={styles.primaryButton} disabled={!canAsk}>
            {isAsking ? "Researching..." : "Run research"}
          </button>

          <div className={styles.progressArea}>
            <p className={styles.sectionLabel}>Progress</p>
            <div className={styles.pillRow}>
              {answerState.stages.length ? (
                answerState.stages.map((stage, index) => (
                  <span className={styles.pill} key={`${stage}-${index}`}>
                    {stage}
                  </span>
                ))
              ) : (
                <span className={styles.mutedText}>No research run yet.</span>
              )}
            </div>
          </div>

          {answerState.error ? (
            <p className={styles.errorText}>{answerState.error}</p>
          ) : null}
        </form>
      </section>

      <section className={styles.outputCard}>
        <div className={styles.cardHeader}>
          <h2>Answer</h2>
          <span className={styles.badge}>
            {answerState.citations.length} citation
            {answerState.citations.length === 1 ? "" : "s"}
          </span>
        </div>

        <p className={styles.answerText}>
          {answerState.text || "Your answer will appear here after the research run completes."}
        </p>

        <div className={styles.citationList}>
          {answerState.citations.map((citation, index) => (
            <article className={styles.citationCard} key={`${citation.chunk_id}-${index}`}>
              <p className={styles.citationTitle}>[{index + 1}] {citation.source_ref}</p>
              <p className={styles.citationMeta}>
                relevance {citation.relevance_score.toFixed(4)}
              </p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
