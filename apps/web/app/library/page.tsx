/**
 * app/library/page.tsx
 * --------------------
 * Purpose:    Library route — lists uploaded documents with delete action.
 * Dependencies: api/use-documents.ts, library.module.css
 * Scope:      Phase 2 library data.
 */

"use client";

import { useDeleteDocument, useDocuments } from "@/features/research/api/use-documents";
import styles from "./library.module.css";

function StatusBadge({ status }: { status: string }) {
  return <span className={`${styles.badge} ${styles[status] ?? ""}`}>{status}</span>;
}

export default function LibraryPage() {
  const { data, isLoading, error } = useDocuments();
  const deleteMutation = useDeleteDocument();

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

      <ul className={styles.list}>
        {data.documents.map((doc) => (
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
