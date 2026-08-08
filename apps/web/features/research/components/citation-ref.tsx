/**
 * features/research/components/citation-ref.tsx
 * ---------------------------------------------
 * Purpose:    Superscript [n] citation button with hover popover.
 *             Popover shows source_ref + relevance + full chunk text.
 *             Code files (by extension) render with syntax highlighting.
 * Dependencies: citation-ref.module.css, lib/utils.ts, api/use-chunk.ts,
 *               react-syntax-highlighter
 * Scope:      Answer panel inline citations.
 */

"use client";

import { useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { useChunk } from "../api/use-chunk";
import { detectLanguage, isCodeFile } from "../utils/detect-language";
import styles from "./citation-ref.module.css";

interface CitationRefProps {
  index: number;
  chunkId: string;
  sourceRef: string;
  relevanceScore: number;
}

function PopoverContent({
  index,
  chunkId,
  sourceRef,
  relevanceScore,
}: {
  index: number;
  chunkId: string;
  sourceRef: string;
  relevanceScore: number;
}) {
  const { data: chunk, isLoading, error } = useChunk(chunkId);
  const codeFile = isCodeFile(sourceRef);
  const language = detectLanguage(sourceRef);

  function renderText(text: string) {
    if (codeFile) {
      return (
        <SyntaxHighlighter
          language={language}
          style={oneDark}
          customStyle={{
            margin: 0,
            fontSize: "12px",
            lineHeight: "1.55",
            borderRadius: "6px",
            maxHeight: "240px",
          }}
          showLineNumbers
          lineNumberStyle={{ fontSize: "10px", opacity: 0.4 }}
        >
          {text}
        </SyntaxHighlighter>
      );
    }
    return <p className={styles.popoverText}>{text}</p>;
  }

  return (
    <div className={styles.popover} role="tooltip">
      <div className={styles.popoverHeader}>
        <span className={styles.popoverIndex}>SRC {index}</span>
        <data className={styles.popoverScore}>{relevanceScore.toFixed(4)}</data>
      </div>
      <p className={styles.popoverSource}>{sourceRef}</p>

      <div className={styles.popoverTextSection}>
        {isLoading && <p className={styles.popoverHint}>Loading passage…</p>}
        {error && <p className={styles.popoverHint}>Failed to load passage.</p>}
        {chunk && renderText(chunk.text)}
        {!isLoading && !error && !chunk && (
          <p className={styles.popoverHint}>Full text unavailable.</p>
        )}
      </div>
    </div>
  );
}

function InlineRef({
  index,
  chunkId,
  sourceRef,
  relevanceScore,
}: CitationRefProps) {
  const [open, setOpen] = useState(false);

  function renderPopover() {
    if (!open) return null;
    return (
      <PopoverContent
        index={index}
        chunkId={chunkId}
        sourceRef={sourceRef}
        relevanceScore={relevanceScore}
      />
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

export function CitationRef(props: CitationRefProps) {
  return <InlineRef {...props} />;
}
