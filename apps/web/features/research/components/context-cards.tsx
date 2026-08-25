/**
 * features/research/components/context-cards.tsx
 * ----------------------------------------------
 * Purpose:    Sources panel under a settled answer — one card per unique
 *             citation chunk: index, document, relevance, excerpt. Excerpt
 *             reuses useChunk so cards share the react-query cache the
 *             citation popovers already warm.
 * Dependencies: api/use-chunk.ts, utils/parse-citations.ts (ADR-009 styling)
 * Scope:      Research chat answer sources panel.
 */

"use client";

import { useChunk } from "../api/use-chunk";
import type { GroupedCitation } from "../utils/parse-citations";

/** File-type chip color/label derived from the document name. */
function fileBadge(document: string): { label: string; className: string } {
  const ext = document.toLowerCase().split(".").pop() ?? "";
  if (ext === "pdf") return { label: "PDF", className: "bg-red" };
  if (ext === "csv") return { label: "CSV", className: "bg-green" };
  if (ext === "wav" || ext === "mp3") return { label: "AU", className: "bg-orange" };
  if (ext === "md" || ext === "txt") return { label: "MD", className: "bg-accent" };
  return { label: "DOC", className: "bg-ink-3" };
}

function ContextCard({ citation, order }: { citation: GroupedCitation; order: number }) {
  const { data: chunk, isLoading, error } = useChunk(citation.chunkId);
  const badge = fileBadge(citation.document);

  return (
    <article
      className="flex min-h-[140px] flex-col justify-between overflow-hidden rounded-card border border-line bg-surface p-3.5 shadow-card transition-all duration-200 hover:border-line-strong"
      style={{ animation: `fade-up 400ms var(--ease-out-expo) ${Math.min(order, 6) * 70}ms both` }}
    >
      <div>
        <header className="flex items-center justify-between gap-2 border-b border-line/60 pb-2">
          <div className="flex min-w-0 items-center gap-2 text-[13px] font-medium text-ink">
            <span
              className={`flex size-4 shrink-0 items-center justify-center rounded-[4px] ${badge.className} text-[8px] font-bold text-white`}
              aria-hidden="true"
            >
              {badge.label}
            </span>
            <span className="truncate font-medium text-ink" title={citation.document}>
              {citation.document}
            </span>
          </div>
          <span className="shrink-0 rounded-full bg-inset px-2 py-0.5 text-[11px] font-medium text-ink-3 tabular-nums shadow-hairline">
            SRC {citation.index} · {(citation.relevanceScore * 100).toFixed(0)}%
          </span>
        </header>

        <p className="mt-2.5 text-[12.5px] leading-relaxed text-ink-2 line-clamp-4 [overflow-wrap:anywhere]">
          {isLoading ? (
            <span className="italic text-ink-3">Loading passage excerpt…</span>
          ) : error ? (
            <span className="italic text-ink-3">Passage excerpt currently unavailable.</span>
          ) : (
            chunk?.text ?? <span className="italic text-ink-3">No excerpt recorded.</span>
          )}
        </p>
      </div>

      <footer className="mt-3 flex items-center justify-between border-t border-line/40 pt-2 text-[11px] text-ink-3">
        <span className="font-mono text-ink-3">chunk {citation.chunkId.slice(0, 8)}</span>
        {typeof chunk?.text === "string" && (
          <span className="tabular-nums">{chunk.text.length.toLocaleString()} chars</span>
        )}
      </footer>
    </article>
  );
}

export function ContextCards({ citations }: { citations: GroupedCitation[] }) {
  if (citations.length === 0) return null;

  return (
    <section
      className="mt-6 flex w-full flex-col gap-3"
      aria-label="Answer sources"
      style={{ animation: "fade-in 400ms ease-out both" }}
    >
      <div className="flex items-center justify-between border-b border-line/40 pb-2">
        <div className="flex items-center gap-2">
          <h3 className="text-[14px] font-semibold tracking-tight text-ink">Retrieved Sources</h3>
          <span className="inline-flex h-5 items-center rounded-full bg-inset px-2 text-[11.5px] font-medium text-accent-ink shadow-hairline tabular-nums">
            {citations.length}
          </span>
        </div>
        <span className="text-[11.5px] text-ink-3">Evidence chunks cited in answer</span>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {citations.map((citation, i) => (
          <ContextCard key={citation.index} citation={citation} order={i} />
        ))}
      </div>
    </section>
  );
}
