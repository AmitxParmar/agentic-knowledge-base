/**
 * features/research/api/use-documents.ts
 * --------------------------------------
 * Purpose:    Document list query + delete mutation.
 * Dependencies: @tanstack/react-query, research-service.ts
 * Scope:      Library page data.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteDocument, listDocuments } from "../research-service";

export function useDocuments() {
  return useQuery({
    queryKey: ["documents"] as const,
    queryFn: () => listDocuments(),
  });
}

export function useDeleteDocument() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (documentId: string) => deleteDocument(documentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}
