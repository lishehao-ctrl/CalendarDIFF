import type { Metadata } from "next";
import { LocaleProvider } from "@/lib/i18n/provider";
import "./globals.css";

export const metadata: Metadata = {
  title: "CalendarDIFF Console",
  description: "Modern frontend shell for CalendarDIFF operations"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-[var(--font-body)] text-ink">
        <LocaleProvider>{children}</LocaleProvider>
      </body>
    </html>
  );
}
