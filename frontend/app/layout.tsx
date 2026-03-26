import type { Metadata } from "next";
import { cookies } from "next/headers";
import { LocaleProvider } from "@/lib/i18n/provider";
import { LOCALE_COOKIE_KEY, normalizeLocale } from "@/lib/i18n/locales";
import "./globals.css";

export const metadata: Metadata = {
  title: "CalendarDIFF",
  description: "CalendarDIFF"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const initialLocale = normalizeLocale(cookies().get(LOCALE_COOKIE_KEY)?.value) || "en";

  return (
    <html lang={initialLocale}>
      <body className="font-[var(--font-body)] text-ink">
        <LocaleProvider initialLocale={initialLocale}>{children}</LocaleProvider>
      </body>
    </html>
  );
}
