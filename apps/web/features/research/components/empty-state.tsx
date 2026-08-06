/**
 * features/research/components/empty-state.tsx
 * --------------------------------------------
 * Purpose:    Reusable empty state for placeholders (library, runs, no-answer).
 * Dependencies: empty-state.module.css
 * Scope:      Shared across research, library, runs.
 */

import styles from "./empty-state.module.css";

interface EmptyStateProps {
  title: string;
  description: string;
}

export function EmptyState({ title, description }: EmptyStateProps) {
  return (
    <div className={styles.container}>
      <p className={styles.title}>{title}</p>
      <p className={styles.description}>{description}</p>
    </div>
  );
}
