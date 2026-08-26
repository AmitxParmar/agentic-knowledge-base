/**
 * app/layout.tsx
 * --------------
 * Purpose:    Root layout — fonts, metadata, global providers.
 * Dependencies: next/font/local, components/providers
 * Scope:      Applied to every route.
 */

import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { Providers } from "@/components/providers";
import { SiteHeader } from "@/components/site-header";

const geistSans = localFont({
  src: "./fonts/GeistVF.woff",
  variable: "--font-geist-sans",
});

const geistMono = localFont({
  src: "./fonts/GeistMonoVF.woff",
  variable: "--font-geist-mono",
});

export const metadata: Metadata = {
  title: "Agentic Research Workspace",
  description: "Upload documents, run research, and inspect citation-backed answers.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`} suppressHydrationWarning>
      <body className="flex h-screen w-screen flex-col overflow-hidden bg-page text-ink antialiased">
        <Providers>
          <SiteHeader />
          <div className="flex flex-1 min-h-0 flex-col overflow-hidden">
            {children}
          </div>
        </Providers>
      </body>
    </html>
  );
}
