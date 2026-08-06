/**
 * features/research/research-service.ts
 * -------------------------------------
 * Purpose:    Fetch wrapper that injects the workspace-id header
 *             on every request. All feature API calls go through here.
 * Dependencies: lib/env.ts, hooks/use-workspace-id.ts
 * Scope:      Research feature data access.
 */

import { API_BASE_URL } from "@/lib/env";

export function getWorkspaceHeaders(): Record<string, string> {
  return { "X-Workspace-Id": "00000000-0000-0000-0000-000000000001" };
}

export interface JobStatus {
  job_id: string;
  document_id: string;
  stage: "queued" | "extracting" | "chunking" | "embedding" | "done" | "failed";
  error: string | null;
}

export interface RunDetail {
  run_id: string;
  question: string;
  answer: string | null;
  status: "running" | "complete" | "failed";
  citations: Array<{ chunk_id: string }>;
  created_at: string;
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const response = await fetch(`${API_BASE_URL}/api/ingestion/jobs/${jobId}`, {
    method: "GET",
    headers: getWorkspaceHeaders(),
  });

  if (!response.ok) {
    throw new Error(`Job status failed: ${response.statusText}`);
  }

  return response.json();
}

export async function getRunDetail(runId: string): Promise<RunDetail> {
  const response = await fetch(`${API_BASE_URL}/api/research/runs/${runId}`, {
    method: "GET",
    headers: getWorkspaceHeaders(),
  });

  if (!response.ok) {
    throw new Error(`Run detail failed: ${response.statusText}`);
  }

  return response.json();
}

export async function uploadDocument(
  file: File,
  sourceType: "pdf" | "repo" | "audio",
): Promise<{ document_id: string; job_id: string; status: string; message: string }> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("source_type", sourceType);

  const response = await fetch(`${API_BASE_URL}/api/ingestion/upload`, {
    method: "POST",
    headers: getWorkspaceHeaders(),
    body: formData,
  });

  if (!response.ok) {
    throw new Error(`Upload failed: ${response.statusText}`);
  }

  return response.json();
}
