/**
 * features/research/components/answer-panel.tsx
 * ---------------------------------------------
 * Purpose:    Displays the answer text with inline citation refs, plus a
 *             citation list below.
 * Dependencies: answer-panel.module.css, citation-ref.tsx, utils/parse-citations.ts
 * Scope:      Research page answer section.
 */

import { CitationRef } from "./citation-ref";
import { groupCitations } from "../utils/parse-citations";
import type { Citation } from "../utils/ws-adapter";
import styles from "./answer-panel.module.css";

interface AnswerPanelProps {
  answer: string | null;
  citations: Citation[];
}

export function AnswerPanel({ answer, citations }: AnswerPanelProps) {
  const grouped = groupCitations(citations);

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <h2 className={styles.title}>Answer</h2>
        <span className={styles.badge}>
          {grouped.length} citation{grouped.length === 1 ? "" : "s"}
        </span>
      </div>

      {answer ? (
        <div className={styles.answer}>
          {answer.split(/(\[\d+\])/g).map((segment, index) => {
            const match = segment.match(/^\[(\d+)\]$/);
            if (match && match[1]) {
              const citationIndex = parseInt(match[1], 10);
              const citation = grouped.find((c) => c.index === citationIndex);
              if (citation) {
                return (
                  <CitationRef
                    key={index}
                    index={citation.index}
                    chunkId={citation.chunkId}
                    sourceRef={citation.sourceRef}
                    relevanceScore={citation.relevanceScore}
                  />
                );
              }
            }
            return <span key={index}>{segment}</span>;
          })}
        </div>
      ) : (
        <p className={styles.placeholder}>
          Your answer will appear here after the research run completes.
        </p>
      )}

      {grouped.length > 0 && (
        <div className={styles.citations}>
          <p className={styles.citationsLabel}>Sources</p>
          {grouped.map((citation) => (
            <CitationRef
              key={citation.chunkId || citation.index}
              index={citation.index}
              chunkId={citation.chunkId}
              sourceRef={citation.sourceRef}
              relevanceScore={citation.relevanceScore}
            />
          ))}
        </div>
      )}
    </div>
  );
}
