import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/app-shell";

export const metadata: Metadata = {
  title: "CalendarDIFF Console",
  description: "Modern frontend shell for CalendarDIFF operations"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-[var(--font-body)] text-ink">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
