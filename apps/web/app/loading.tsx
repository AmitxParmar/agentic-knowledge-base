/**
 * app/loading.tsx
 * ---------------
 * Purpose:    Route-level loading skeleton (shown during suspense/streaming).
 * Dependencies: none
 * Scope:      Global.
 */

export default function Loading() {
  return (
    <main
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "60vh",
        fontSize: "14px",
        color: "hsl(var(--muted-foreground))",
      }}
    >
      Loading workspace...
    </main>
  );
}
