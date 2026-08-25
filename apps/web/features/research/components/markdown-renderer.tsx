/**
 * features/research/components/markdown-renderer.tsx
 * --------------------------------------------------
 * Purpose:    Render markdown content cleanly with structured headings, tables,
 *             lists, code blocks, blockquotes, and inline [n] citation tags.
 * Dependencies: citation-ref.tsx, utils/parse-citations.ts
 * Scope:      Research chat answer rendering.
 */

"use client";

import { CitationRef } from "./citation-ref";
import type { GroupedCitation } from "../utils/parse-citations";

interface MarkdownRendererProps {
  content: string;
  citations: GroupedCitation[];
}

type Block =
  | { type: "heading"; level: number; text: string }
  | { type: "code"; lang: string; text: string }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "blockquote"; text: string }
  | { type: "hr" }
  | { type: "paragraph"; text: string };

function parseMarkdownBlocks(markdown: string): Block[] {
  const lines = markdown.split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const rawLine = lines[i];
    if (rawLine === undefined) break;

    const line = rawLine;

    if (!line.trim()) {
      i++;
      continue;
    }

    // Code block ```
    if (line.trim().startsWith("```")) {
      const lang = line.trim().slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length) {
        const cur = lines[i];
        if (cur === undefined || cur.trim().startsWith("```")) break;
        codeLines.push(cur);
        i++;
      }
      if (i < lines.length) i++;
      blocks.push({ type: "code", lang, text: codeLines.join("\n") });
      continue;
    }

    // Heading #
    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch && headingMatch[1] && headingMatch[2]) {
      blocks.push({
        type: "heading",
        level: headingMatch[1].length,
        text: headingMatch[2].trim(),
      });
      i++;
      continue;
    }

    // Table line starting and ending with |
    if (line.trim().startsWith("|") && line.trim().endsWith("|")) {
      const tableLines: string[] = [];
      while (i < lines.length) {
        const cur = lines[i];
        if (cur === undefined || !cur.trim().startsWith("|") || !cur.trim().endsWith("|")) break;
        tableLines.push(cur.trim());
        i++;
      }
      const rows = tableLines.map((tl) =>
        tl
          .slice(1, -1)
          .split("|")
          .map((cell) => cell.trim()),
      );
      const isDelimiterRow = (r: string[]) => r.every((cell) => /^[-:\s]+$/.test(cell));
      const hasHeader = rows.length > 1 && isDelimiterRow(rows[1] ?? []);
      const headers = hasHeader ? (rows[0] ?? []) : [];
      const dataRows = hasHeader ? rows.slice(2) : rows;

      blocks.push({ type: "table", headers, rows: dataRows });
      continue;
    }

    // Unordered list - or *
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length) {
        const cur = lines[i];
        if (cur === undefined || !/^\s*[-*]\s+/.test(cur)) break;
        items.push(cur.replace(/^\s*[-*]\s+/, "").trim());
        i++;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    // Ordered list 1.
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length) {
        const cur = lines[i];
        if (cur === undefined || !/^\s*\d+\.\s+/.test(cur)) break;
        items.push(cur.replace(/^\s*\d+\.\s+/, "").trim());
        i++;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    // Blockquote >
    if (line.trim().startsWith(">")) {
      const quoteLines: string[] = [];
      while (i < lines.length) {
        const cur = lines[i];
        if (cur === undefined || !cur.trim().startsWith(">")) break;
        quoteLines.push(cur.trim().replace(/^>\s*/, ""));
        i++;
      }
      blocks.push({ type: "blockquote", text: quoteLines.join("\n") });
      continue;
    }

    // Horizontal rule --- or ***
    if (/^(\*{3,}|-{3,}|_{3,})$/.test(line.trim())) {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    // Paragraph
    const pLines: string[] = [];
    while (i < lines.length) {
      const cur = lines[i];
      if (
        cur === undefined ||
        !cur.trim() ||
        cur.trim().startsWith("```") ||
        cur.match(/^(#{1,6})\s+/) ||
        (cur.trim().startsWith("|") && cur.trim().endsWith("|")) ||
        /^\s*[-*]\s+/.test(cur) ||
        /^\s*\d+\.\s+/.test(cur) ||
        cur.trim().startsWith(">") ||
        /^(\*{3,}|-{3,}|_{3,})$/.test(cur.trim())
      ) {
        break;
      }
      pLines.push(cur);
      i++;
    }
    if (pLines.length > 0) {
      blocks.push({ type: "paragraph", text: pLines.join(" ") });
    }
  }

  return blocks;
}

function parseInlineMarkdown(text: string, keyPrefix: string | number) {
  const regex = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  const tokens = text.split(regex);

  return tokens.map((token, index) => {
    const key = `${keyPrefix}-${index}`;
    if (token.startsWith("**") && token.endsWith("**") && token.length > 4) {
      return (
        <strong key={key} className="font-semibold text-ink">
          {token.slice(2, -2)}
        </strong>
      );
    }
    if (token.startsWith("*") && token.endsWith("*") && token.length > 2) {
      return (
        <em key={key} className="italic text-ink-2">
          {token.slice(1, -1)}
        </em>
      );
    }
    if (token.startsWith("`") && token.endsWith("`") && token.length > 2) {
      return (
        <code
          key={key}
          className="rounded border border-line bg-inset px-1.5 py-0.5 font-mono text-[12.5px] text-accent-ink"
        >
          {token.slice(1, -1)}
        </code>
      );
    }
    return <span key={key}>{token}</span>;
  });
}

function renderInlineContent(text: string, citations: GroupedCitation[]) {
  const citationParts = text.split(/(\[\d+\])/g);

  return citationParts.map((part, pIdx) => {
    const match = part.match(/^\[(\d+)\]$/);
    if (match?.[1]) {
      const idx = parseInt(match[1], 10);
      const citation = citations.find((c) => c.index === idx);
      if (citation?.chunkId && citation.sourceRef) {
        return (
          <CitationRef
            key={`cit-${pIdx}`}
            index={citation.index}
            chunkId={citation.chunkId}
            sourceRef={citation.sourceRef}
            relevanceScore={citation.relevanceScore}
          />
        );
      }
      return <span key={`cit-${pIdx}`}>{part}</span>;
    }

    return parseInlineMarkdown(part, pIdx);
  });
}

export function MarkdownRenderer({ content, citations }: MarkdownRendererProps) {
  const blocks = parseMarkdownBlocks(content);

  return (
    <div className="flex flex-col gap-3 text-[15px] leading-[1.75] text-ink [overflow-wrap:anywhere] break-words">
      {blocks.map((block, idx) => {
        if (block.type === "heading") {
          if (block.level === 1) {
            return (
              <h1 key={idx} className="mt-5 mb-2 text-xl font-bold tracking-tight text-ink">
                {renderInlineContent(block.text, citations)}
              </h1>
            );
          }
          if (block.level === 2) {
            return (
              <h2 key={idx} className="mt-4 mb-2 border-b border-line pb-1.5 text-lg font-semibold tracking-tight text-ink">
                {renderInlineContent(block.text, citations)}
              </h2>
            );
          }
          return (
            <h3 key={idx} className="mt-3 mb-1.5 text-base font-semibold text-ink">
              {renderInlineContent(block.text, citations)}
            </h3>
          );
        }

        if (block.type === "code") {
          return (
            <pre
              key={idx}
              className="my-2.5 overflow-x-auto rounded-control border border-line bg-inset p-3.5 font-mono text-[13px] leading-relaxed text-ink-2 shadow-inner"
            >
              <code>{block.text}</code>
            </pre>
          );
        }

        if (block.type === "table") {
          return (
            <div key={idx} className="my-3 overflow-x-auto rounded-control border border-line bg-surface shadow-card">
              <table className="w-full text-left text-[13.5px]">
                {block.headers.length > 0 && (
                  <thead className="border-b border-line bg-surface-raised font-semibold text-ink">
                    <tr>
                      {block.headers.map((h, hIdx) => (
                        <th key={hIdx} className="border-r border-line/40 px-3.5 py-2.5 last:border-r-0">
                          {renderInlineContent(h, citations)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                )}
                <tbody>
                  {block.rows.map((row, rIdx) => (
                    <tr key={rIdx} className="border-b border-line/40 transition-colors last:border-b-0 hover:bg-hover">
                      {row.map((cell, cIdx) => (
                        <td key={cIdx} className="border-r border-line/40 px-3.5 py-2 text-ink-2 last:border-r-0">
                          {renderInlineContent(cell, citations)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }

        if (block.type === "ul") {
          return (
            <ul key={idx} className="my-1.5 flex flex-col gap-1.5 pl-5 list-disc text-ink-2">
              {block.items.map((item, itemIdx) => (
                <li key={itemIdx} className="pl-1">
                  {renderInlineContent(item, citations)}
                </li>
              ))}
            </ul>
          );
        }

        if (block.type === "ol") {
          return (
            <ol key={idx} className="my-1.5 flex flex-col gap-1.5 pl-5 list-decimal text-ink-2">
              {block.items.map((item, itemIdx) => (
                <li key={itemIdx} className="pl-1">
                  {renderInlineContent(item, citations)}
                </li>
              ))}
            </ol>
          );
        }

        if (block.type === "blockquote") {
          return (
            <blockquote
              key={idx}
              className="my-2 border-l-2 border-accent bg-accent-tint/30 px-3.5 py-2.5 italic text-ink-2 rounded-r-control"
            >
              {renderInlineContent(block.text, citations)}
            </blockquote>
          );
        }

        if (block.type === "hr") {
          return <hr key={idx} className="my-4 border-line" />;
        }

        return (
          <p key={idx} className="text-ink leading-[1.75]">
            {renderInlineContent(block.text, citations)}
          </p>
        );
      })}
    </div>
  );
}
