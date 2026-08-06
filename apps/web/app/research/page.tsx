/**
 * app/research/page.tsx
 * ---------------------
 * Purpose:    Research page — full core loop (upload → ask → cited answer).
 * Dependencies: features/research/components/research-workspace.tsx
 * Scope:      MVP home page.
 */

import { ResearchWorkspace } from "@/features/research/components/research-workspace";

export default function ResearchPage() {
  return <ResearchWorkspace />;
}
