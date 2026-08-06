/**
 * features/research/utils/parse-citations.ts
 * ------------------------------------------
 * Purpose:    Group and order citations by document + chunk for display.
 * Dependencies: ws-adapter.ts (Citation type)
 * Scope:      Citation display logic.
 */

import type { Citation } from "./ws-adapter";

export interface GroupedCitation {
  index: number;
  chunkId: string;
  sourceRef: string;
  relevanceScore: number;
  document: string;
}

export function groupCitations(citations: Citation[]): GroupedCitation[] {
  const seen = new Map<string, number>();
  let nextIndex = 1;

  return citations.map((citation) => {
    const existing = seen.get(citation.chunk_id);
    if (existing !== undefined) {
      return {
        index: existing,
        chunkId: citation.chunk_id,
        sourceRef: citation.source_ref,
        relevanceScore: citation.relevance_score,
        document: extractDocument(citation.source_ref),
      };
    }

    const currentIndex = nextIndex++;
    seen.set(citation.chunk_id, currentIndex);

    return {
      index: currentIndex,
      chunkId: citation.chunk_id,
      sourceRef: citation.source_ref,
      relevanceScore: citation.relevance_score,
      document: extractDocument(citation.source_ref),
    };
  });
}

function extractDocument(sourceRef: string): string {
  if (!sourceRef) return "Unknown source";
  const parts = sourceRef.split("/");
  return parts[parts.length - 1] || sourceRef;
}
