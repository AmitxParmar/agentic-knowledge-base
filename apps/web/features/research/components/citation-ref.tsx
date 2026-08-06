/**
 * features/research/components/citation-ref.tsx
 * ---------------------------------------------
 * Purpose:    Superscript [n] citation button with hover popover
 *             (source_ref + relevance score).
 * Dependencies: citation-ref.module.css, lib/utils.ts
 * Scope:      Answer panel inline citations.
 */

"use client";

import { useState } from "react";
import styles from "./citation-ref.module.css";

interface CitationRefProps {
  index: number;
  sourceRef: string;
  relevanceScore: number;
}

export function CitationRef({ index, sourceRef, relevanceScore }: CitationRefProps) {
  const [open, setOpen] = useState(false);

  function renderPopover() {
    if (!open) return null;
    return (
      <div className={styles.popover} role="tooltip">
        <div className={styles.popoverHeader}>
          <span className={styles.popoverIndex}>[{index}]</span>
          <span className={styles.popoverScore}>
            {relevanceScore.toFixed(4)}
          </span>
        </div>
        <p className={styles.popoverSource}>{sourceRef}</p>
        <p className={styles.popoverHint}>Full text unavailable in MVP</p>
      </div>
    );
  }

  return (
    <span className={styles.wrapper}>
      <button
        type="button"
        className={styles.ref}
        aria-label={`Citation ${index}: ${sourceRef}`}
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
      >
        {index}
      </button>
      {renderPopover()}
    </span>
  );
}
