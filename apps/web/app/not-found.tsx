/**
 * app/not-found.tsx
 * -----------------
 * Purpose:    404 page for unmatched routes.
 * Dependencies: next/link
 * Scope:      Global.
 */

import Link from "next/link";

export default function NotFound() {
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
      <p style={{ fontSize: "16px", fontWeight: 600 }}>Page not found</p>
      <p style={{ fontSize: "14px", color: "hsl(var(--muted-foreground))" }}>
        The page you&apos;re looking for doesn&apos;t exist.
      </p>
      <Link
        href="/research"
        style={{
          fontSize: "14px",
          color: "hsl(var(--accent))",
          textDecoration: "underline",
        }}
      >
        Go to Research
      </Link>
    </main>
  );
}
