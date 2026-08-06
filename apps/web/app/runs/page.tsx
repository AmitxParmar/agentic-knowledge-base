/**
 * app/runs/page.tsx
 * -----------------
 * Purpose:    Runs route — placeholder until backend list endpoint lands.
 * Dependencies: features/research/components/empty-state.tsx
 * Scope:      Phase 1 placeholder.
 */

import { EmptyState } from "@/features/research/components/empty-state";

export default function RunsPage() {
  return (
    <EmptyState
      title="Run History"
      description="Past research runs will appear here once the history API is available."
    />
  );
}
