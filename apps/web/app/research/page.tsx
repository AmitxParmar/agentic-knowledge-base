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

  return (
    <>
      {!ready && <ColdStartSplash onReady={() => setReady(true)} />}
      <main
        style={{ display: ready ? "block" : "none" }}
        aria-hidden={!ready}
      >
        <ResearchWorkspace />
      </main>
    </>
  );
}
