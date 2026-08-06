/**
 * app/error.tsx
 * -------------
 * Purpose:    Route-level error boundary. Must be a client component.
 * Dependencies: none
 * Scope:      Global.
 */

"use client";

interface ErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function Error({ error, reset }: ErrorProps) {
  return (
    <main
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "16px",
        minHeight: "60vh",
        padding: "32px",
        textAlign: "center",
      }}
    >
      <p style={{ fontSize: "16px", fontWeight: 600 }}>Something went wrong</p>
      <p style={{ fontSize: "14px", color: "hsl(var(--muted-foreground))", maxWidth: "480px" }}>
        {error.message}
      </p>
      <button
        onClick={reset}
        style={{
          height: "40px",
          padding: "0 24px",
          fontSize: "14px",
          fontWeight: 500,
          color: "hsl(var(--accent-foreground))",
          background: "hsl(var(--accent))",
          border: "none",
          borderRadius: "8px",
          cursor: "pointer",
        }}
      >
        Try again
      </button>
    </main>
  );
}
