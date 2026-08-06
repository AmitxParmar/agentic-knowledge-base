/**
 * app/library/page.tsx
 * --------------------
 * Purpose:    Library route — placeholder until backend list endpoint lands.
 * Dependencies: components/empty-state.tsx
 * Scope:      Phase 1 placeholder.
 */

import { EmptyState } from "@/features/research/components/empty-state";

export default function LibraryPage() {
  return (
    <EmptyState
      title="Library"
      description="Document management connects here once the list API is available."
    />
  );
}
