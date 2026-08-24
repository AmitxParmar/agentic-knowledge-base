/**
 * features/research/components/context-cards.tsx
 * ----------------------------------------------
 * Purpose:    Grid of retrieved-chunk cards for the current answer's sources —
 *             one card per unique citation: SRC index, document, relevance,
 *             excerpt. Excerpt reuses useChunk so cards share the react-query
 *             cache the citation popovers already warm.
 * Dependencies: context-cards.module.css, api/use-chunk.ts, utils/parse-citations.ts
 * Scope:      Research chat answer sources panel.
 */

"use client";

import { useChunk } from "../api/use-chunk";
import type { GroupedCitation } from "../utils/parse-citations";
import styles from "./context-cards.module.css";

function ContextCard({ citation }: { citation: GroupedCitation }) {
  const { data: chunk, isLoading, error } = useChunk(citation.chunkId);

  return (
    <article className={styles.card}>
      <header className={styles.cardHeader}>
        <span className={styles.cardIndex}>SRC {citation.index}</span>
        <data className={styles.cardScore}>{citation.relevanceScore.toFixed(4)}</data>
      </header>
      <p className={styles.cardSource}>{citation.document}</p>
      {isLoading && <p className={styles.cardExcerpt}>Loading passage…</p>}
      {error && <p className={styles.cardExcerpt}>Passage unavailable.</p>}
      {chunk && <p className={styles.cardExcerpt}>{chunk.text}</p>}
    </article>
  );
}

export function ContextCards({ citations }: { citations: GroupedCitation[] }) {
  if (citations.length === 0) return null;

  return (
    <section className={styles.panel} aria-label="Answer sources">
      <p className={styles.label}>
        SOURCES / {citations.length} CHUNK{citations.length === 1 ? "" : "S"}
      </p>
      <div className={styles.grid}>
        {citations.map((citation) => (
          <ContextCard key={`${citation.index}-${citation.chunkId}`} citation={citation} />
        ))}
      </div>
    </section>
  );
}
