/**
 * features/research/api/use-chunk.ts
 * ----------------------------------
 * Purpose:    Fetch a single chunk's full text by ID.
 * Dependencies: @tanstack/react-query, research-service.ts
 * Scope:      Citation popover full-text display.
 */

import { useQuery } from "@tanstack/react-query";
import { getChunk } from "../research-service";

export function useChunk(chunkId: string | null) {
  return useQuery({
    queryKey: ["chunk", chunkId] as const,
    queryFn: () => getChunk(chunkId!),
    enabled: chunkId !== null,
  });
}
