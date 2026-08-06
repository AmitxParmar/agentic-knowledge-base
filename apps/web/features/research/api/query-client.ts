/**
 * features/research/api/query-client.ts
 * -------------------------------------
 * Purpose:    Global React Query client with conservative defaults.
 * Dependencies: @tanstack/react-query
 * Scope:      App-wide (one client instance).
 */

import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 5_000,
      refetchOnWindowFocus: false,
    },
  },
});
