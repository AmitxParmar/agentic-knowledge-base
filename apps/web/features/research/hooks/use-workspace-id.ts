/**
 * features/research/hooks/use-workspace-id.ts
 * --------------------------------------------
 * Purpose:    MVP seam for workspace scoping.
 *             Returns the dev workspace ID. Replace with JWT decode when
 *             RBAC ships (see ADR for auth).
 * Dependencies: none
 * Scope:      Used by all API calls to inject the workspace header.
 */

import { useCallback } from "react";

const DEV_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001";

export function useWorkspaceId(): string {
  return DEV_WORKSPACE_ID;
}

export function useWorkspaceHeaders(): () => Record<string, string> {
  const workspaceId = useWorkspaceId();
  return useCallback(
    () => ({
      "X-Workspace-Id": workspaceId,
    }),
    [workspaceId],
  );
}
