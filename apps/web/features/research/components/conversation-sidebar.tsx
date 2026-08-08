/**
 * features/research/components/conversation-sidebar.tsx
 * -----------------------------------------------------
 * Purpose:  Conversation history rail. Lists local thread summaries,
 *           lets the user switch/hard-delete, and announces the current
 *           state in terminal framing. Runs only on local state for now.
 * Dependencies: conversation-sidebar.module.css
 * Scope:    Research workspace left rail.
 */

import type { ConversationMeta } from "../api/use-conversations";
import styles from "./conversation-sidebar.module.css";

interface ConversationSidebarProps {
  threads: ConversationMeta[];
  activeId: string;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

export function ConversationSidebar({
  threads,
  activeId,
  onSelect,
  onDelete,
}: ConversationSidebarProps) {
  return (
    <aside className={styles.sidebar} aria-label="Conversation history">
      <div className={styles.header}>
        <span className={styles.headerLabel}>[ /history ]</span>
        <span className={styles.headerCount}>
          {threads.length} thread{threads.length === 1 ? "" : "s"}
        </span>
      </div>

      <div className={styles.listWrap}>
        <ul className={styles.list} role="listbox" aria-label="Research conversations">
          {threads.map((thread) => (
            <li key={thread.id} className={styles.item}>
              <button
                type="button"
                role="option"
                aria-selected={thread.id === activeId}
                className={`${styles.row} ${thread.id === activeId ? styles.rowActive : ""}`}
                onClick={() => onSelect(thread.id)}
              >
                <span className={styles.rowTitle}>{thread.title}</span>
                <span className={styles.rowMeta}>
                  <data value={thread.updatedAt.toISOString()}>{formatStamp(thread.updatedAt)}</data>
                  <span className={styles.rowCount}>
                    {thread.messageCount} msg{thread.messageCount === 1 ? "" : "s"}
                  </span>
                </span>
              </button>
              <button
                type="button"
                className={styles.delete}
                aria-label={`Delete ${thread.title}`}
                onClick={() => onDelete(thread.id)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className={styles.footer}>
        <span className={styles.hint}>Storage: client-only</span>
      </div>
    </aside>
  );
}

function formatStamp(date: Date): string {
  return `${date.toISOString().slice(11, 19)} UTC`;
}
