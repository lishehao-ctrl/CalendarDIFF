"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { translate } from "@/lib/i18n/runtime";
import type { Locale } from "@/lib/i18n/locales";

export function PublicAuthShell({
  locale,
  onLocaleChange,
  children,
}: {
  locale: Locale;
  onLocaleChange: (locale: Locale) => void;
  children: React.ReactNode;
}) {
  const t = (key: string, vars?: Record<string, string | number | null | undefined>) =>
    translate(key, vars, locale);

  return (
    <div className="min-h-screen bg-transparent px-4 py-8 md:px-8">
      <div className="mx-auto flex min-h-[80vh] max-w-6xl items-center justify-center">
        <div className="grid w-full gap-6 lg:grid-cols-[1.05fr_0.95fr]">
          <Card className="relative overflow-hidden p-8 md:p-10">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.16),transparent_42%),radial-gradient(circle_at_80%_20%,rgba(215,90,45,0.12),transparent_30%)]" />
            <div className="relative">
              <p className="text-xs uppercase tracking-[0.24em] text-[#6d7885]">CalendarDIFF</p>
              <h1 className="mt-4 text-4xl font-semibold leading-tight text-ink">{t("auth.marketingTitle")}</h1>
              <p className="mt-5 max-w-xl text-sm leading-7 text-[#596270]">{t("auth.marketingSummary")}</p>
            </div>
          </Card>

          <div className="space-y-4">
            <Card className="p-4 md:p-5" data-testid="auth-locale-switch">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{t("common.localeLabel")}</p>
                </div>
              <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant={locale === "en" ? "secondary" : "ghost"}
                    aria-pressed={locale === "en"}
                    data-testid="auth-locale-en"
                    onClick={() => onLocaleChange("en")}
                  >
                    {t("common.locales.en")}
                  </Button>
                  <Button
                    size="sm"
                    variant={locale === "zh-CN" ? "secondary" : "ghost"}
                    aria-pressed={locale === "zh-CN"}
                    data-testid="auth-locale-zh-CN"
                    onClick={() => onLocaleChange("zh-CN")}
                  >
                    {t("common.locales.zh-CN")}
                  </Button>
                </div>
              </div>
            </Card>

            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
