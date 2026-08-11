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

export interface DocumentListItem {
  document_id: string;
  source_type: string;
  filename: string;
  processing_status: string;
  created_at: string;
}

export interface DocumentList {
  documents: DocumentListItem[];
  total: number;
}

export interface RunListItem {
  run_id: string;
  question: string;
  status: string;
  created_at: string;
}

export interface RunList {
  runs: RunListItem[];
  total: number;
}

export interface ChunkItem {
  chunk_id: string;
  document_id: string;
  source_ref: string;
  text: string;
  position: number;
}

export async function listDocuments(limit = 50, offset = 0): Promise<DocumentList> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  const response = await fetch(`${API_BASE_URL}/api/ingestion/documents?${params}`, {
    method: "GET",
    headers: getWorkspaceHeaders(),
  });
  if (!response.ok) {
    throw new Error(`List documents failed: ${response.statusText}`);
  }
  return response.json();
}

export async function searchableDocumentsExist(): Promise<boolean> {
  const params = new URLSearchParams({
    processing_status: "done",
    limit: "1",
    offset: "0",
  });
  const response = await fetch(`${API_BASE_URL}/api/ingestion/documents?${params}`, {
    method: "GET",
    headers: getWorkspaceHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Document status check failed: ${response.statusText}`);
  }
  const data = (await response.json()) as DocumentList;
  return data.total > 0;
}

export async function deleteDocument(documentId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/ingestion/documents/${documentId}`, {
    method: "DELETE",
    headers: getWorkspaceHeaders(),
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`Delete document failed: ${response.statusText}`);
  }
}

export async function getChunk(chunkId: string): Promise<ChunkItem> {
  const response = await fetch(`${API_BASE_URL}/api/ingestion/chunks/${chunkId}`, {
    method: "GET",
    headers: getWorkspaceHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Get chunk failed: ${response.statusText}`);
  }
  return response.json();
}

export async function listRuns(limit = 50, offset = 0): Promise<RunList> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  const response = await fetch(`${API_BASE_URL}/api/research/runs?${params}`, {
    method: "GET",
    headers: getWorkspaceHeaders(),
  });
  if (!response.ok) {
    throw new Error(`List runs failed: ${response.statusText}`);
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
