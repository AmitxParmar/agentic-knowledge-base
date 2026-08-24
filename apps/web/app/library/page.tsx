/**
 * app/library/page.tsx
 * --------------------
 * Purpose:    Library route — lists uploaded documents with delete action.
 * Dependencies: api/use-documents.ts, library.module.css
 * Scope:      Phase 2 library data.
 */

"use client";

import { useMemo, useState } from "react";
import { useDeleteDocument, useDocuments } from "@/features/research/api/use-documents";
import styles from "./library.module.css";

function StatusBadge({ status }: { status: string }) {
  return <span className={`${styles.badge} ${styles[status] ?? ""}`}>{status}</span>;
}

export default function LibraryPage() {
  const { data, isLoading, error } = useDocuments();
  const deleteMutation = useDeleteDocument();
  const [statusFilter, setStatusFilter] = useState<string | null>(null);

  // ponytail: chips derived from statuses actually present; no canonical list to maintain
  const statusCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const doc of data?.documents ?? []) {
      counts.set(doc.processing_status, (counts.get(doc.processing_status) ?? 0) + 1);
    }
    return [...counts.entries()];
  }, [data]);

  const visible = data?.documents.filter(
    (doc) => !statusFilter || doc.processing_status === statusFilter,
  );

  if (isLoading) {
    return <p className={styles.empty}>Loading documents…</p>;
  }

  if (error) {
    return (
      <p className={styles.error} role="alert">
        Failed to load documents.
      </p>
    );
  }

  if (!data || data.documents.length === 0) {
    return (
      <div className={styles.container}>
        <h1 className={styles.title}>Library</h1>
        <p className={styles.empty}>No documents yet. Upload one from the Research page.</p>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>Library</h1>
      <p className={styles.subtitle}>
        {data.total} document{data.total === 1 ? "" : "s"}
      </p>

      <div className={styles.filters} role="group" aria-label="Filter by status">
        <button
          type="button"
          className={`${styles.chip} ${statusFilter === null ? styles.chipActive : ""}`}
          onClick={() => setStatusFilter(null)}
          aria-pressed={statusFilter === null}
        >
          All {data.total}
        </button>
        {statusCounts.map(([status, count]) => (
          <button
            key={status}
            type="button"
            className={`${styles.chip} ${statusFilter === status ? styles.chipActive : ""}`}
            onClick={() => setStatusFilter(statusFilter === status ? null : status)}
            aria-pressed={statusFilter === status}
          >
            {status} {count}
          </button>
        ))}
      </div>

      <ul className={styles.list}>
        {(visible ?? []).map((doc) => (
          <li key={doc.document_id} className={styles.item}>
            <div className={styles.itemInfo}>
              <span className={styles.filename}>{doc.filename}</span>
              <div className={styles.itemMeta}>
                <span className={styles.sourceType}>{doc.source_type}</span>
                <StatusBadge status={doc.processing_status} />
              </div>
            </div>
            <button
              type="button"
              className={styles.deleteButton}
              disabled={deleteMutation.isPending}
              onClick={() => deleteMutation.mutate(doc.document_id)}
              aria-label={`Delete ${doc.filename}`}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
