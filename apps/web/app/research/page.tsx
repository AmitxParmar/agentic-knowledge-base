/**
 * app/research/page.tsx
 * ---------------------
 * Purpose:    Research page — gates the workspace behind a cold-start splash
 *             until the server is reachable, then reveals the full loop.
 * Dependencies: cold-start-splash.tsx, research-workspace.tsx
 * Scope:      MVP home page.
 */

"use client";

import { useState } from "react";
import { ColdStartSplash } from "@/features/research/components/cold-start-splash";
import { ResearchWorkspace } from "@/features/research/components/research-workspace";

export default function ResearchPage() {
  const [ready, setReady] = useState(false);

  if (!ready) {
    return <ColdStartSplash onReady={() => setReady(true)} />;
  }

  return (
    <div className="flex flex-1 min-h-0 flex-col overflow-hidden">
      <ResearchWorkspace />
    </div>
  );
}
