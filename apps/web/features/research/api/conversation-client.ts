/**
 * features/research/api/conversation-client.ts
 * --------------------------------------------
 * Purpose:    Thin client for the conversation-threads API. Thread metadata
 *             (id/title) is server-backed; the conversation store uses these
 *             calls to persist thread lifecycle and link research runs.
 * Dependencies: lib/env.ts
 * Scope:      Thread CRUD + run-linking.
 */

import { API_BASE_URL } from "@/lib/env";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface ThreadSummary {
  id: string;
  title: string;
  run_count: number;
  created_at: string;
  updated_at: string;
}

export function listThreads(): Promise<{ threads: ThreadSummary[] }> {
  return request("/api/conversations");
}

export function linkRun(threadId: string, runId: string): Promise<ThreadSummary> {
  return request(`/api/conversations/${threadId}/runs`, {
    method: "POST",
    body: JSON.stringify({ run_id: runId }),
  });
}

export function deleteThread(threadId: string): Promise<void> {
  return request(`/api/conversations/${threadId}`, { method: "DELETE" });
}
