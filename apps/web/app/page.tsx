/**
 * app/page.tsx
 * ------------
 * Purpose:    Root route — redirects to /research.
 * Dependencies: next/navigation redirect
 * Scope:      Entry point.
 */

import { redirect } from "next/navigation";

export default function Home() {
  redirect("/research");
}
