import type { Metadata } from "next";
import Script from "next/script";
import type { CSSProperties } from "react";

import "./globals.css";

const rootFontVars: CSSProperties = {
  "--font-body": '"Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif',
  "--font-heading": '"Trebuchet MS", "Avenir Next", "Segoe UI", sans-serif',
} as CSSProperties;

export const metadata: Metadata = {
  title: "Deadline Diff Watcher UI",
  description: "Operational dashboard for input sync, overrides, and diff review.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" style={rootFontVars}>
      <body className="min-h-screen bg-bg text-ink [font-family:var(--font-body)]">
        <Script src="/ui/app-config.js" strategy="beforeInteractive" />
        <div className="pointer-events-none fixed inset-0 -z-10 bg-atmosphere" />
        <div className="pointer-events-none fixed inset-0 -z-10 grid-overlay" />
        {children}
      </body>
    </html>
  );
}
