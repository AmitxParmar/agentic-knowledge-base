/**
 * features/research/api/use-upload.ts
 * -----------------------------------
 * Purpose:    Upload mutation → POST /api/ingestion/upload.
 *             Returns document_id and job_id for downstream polling.
 * Dependencies: @tanstack/react-query, research-service.ts
 * Scope:      Upload flow.
 */

import { useMutation } from "@tanstack/react-query";
import { uploadDocument } from "../research-service";

export interface UploadResult {
  document_id: string;
  job_id: string;
  status: string;
  message: string;
}

export function useUpload() {
  return useMutation({
    mutationFn: ({ file, sourceType }: { file: File; sourceType: "pdf" | "repo" | "audio" }) =>
      uploadDocument(file, sourceType),
  });
}
