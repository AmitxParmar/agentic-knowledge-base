/**
 * features/research/components/conversation-sidebar.tsx
 * -----------------------------------------------------
 * Purpose:  Conversation history rail. Lists local thread summaries and
 *           lets the user switch or hard-delete them. Runs on local state.
 * Dependencies: none beyond types (ADR-009 styling)
 * Scope:    Research workspace left rail.
 */

import type { ConversationMeta } from "../api/use-conversations";
import { cn } from "@/lib/utils";

interface ConversationSidebarProps {
  threads: ConversationMeta[];
  activeId: string;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onNew: () => void;
}

export function ConversationSidebar({
  threads,
  activeId,
  onSelect,
  onDelete,
  onNew,
}: ConversationSidebarProps) {
  return (
    <aside className="flex h-full min-h-0 flex-1 flex-col select-none" aria-label="Conversation history">
      {/* header */}
      <div className="flex items-center justify-between border-b border-line/40 px-3.5 py-2.5 shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-[11.5px] font-semibold uppercase tracking-wider text-ink-3">
            History
          </span>
          <span className="rounded-full bg-inset px-2 py-0.5 text-[11px] font-medium text-ink-3 tabular-nums shadow-hairline">
            {threads.length}
          </span>
        </div>
        <button
          type="button"
          onClick={onNew}
          title="Start new research thread"
          className="flex h-7 items-center gap-1 rounded-control bg-surface-raised px-2.5 text-[12px] font-medium text-ink transition-colors duration-150 hover:bg-hover hover:text-accent shadow-btn"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
          <span>New</span>
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        <ul role="listbox" aria-label="Research conversations" className="flex flex-col gap-1">
          {threads.map((thread) => {
            const isActive = thread.id === activeId;
            return (
              <li key={thread.id} className="group/item relative">
                <button
                  type="button"
                  role="option"
                  aria-selected={isActive}
                  className={cn(
                    "w-full rounded-control px-3 py-2.5 pr-8 text-left transition-colors duration-150 border-l-2",
                    isActive
                      ? "border-accent bg-surface shadow-card text-ink"
                      : "border-transparent text-ink-2 hover:bg-hover hover:text-ink",
                  )}
                  onClick={() => onSelect(thread.id)}
                  title={thread.title}
                >
                  <span className="block truncate text-[13px] font-medium leading-snug">
                    {thread.title}
                  </span>
                  <span className="mt-1 flex items-center gap-1.5 text-[11px] text-ink-3 tabular-nums">
                    <data value={thread.updatedAt.toISOString()}>{formatStamp(thread.updatedAt)}</data>
                    <span aria-hidden="true">·</span>
                    <span>
                      {thread.messageCount} msg{thread.messageCount === 1 ? "" : "s"}
                    </span>
                  </span>
                </button>
                <button
                  type="button"
                  aria-label={`Delete ${thread.title}`}
                  onClick={() => onDelete(thread.id)}
                  className="absolute right-1.5 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded-control text-ink-3 opacity-0 transition-all duration-150 hover:bg-hover-2 hover:text-red focus-visible:opacity-100 group-hover/item:opacity-100"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
                    <path d="M18 6L6 18M6 6l12 12" />
                  </svg>
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="border-t border-line/40 px-3.5 py-2 text-[11px] text-ink-3">
        History stored locally
      </div>
    </aside>
  );
}

function formatStamp(date: Date): string {
  return `${date.toISOString().slice(11, 19)} UTC`;
}
