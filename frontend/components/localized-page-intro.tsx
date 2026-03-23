"use client";

import { useT } from "@/lib/i18n/use-locale";

export function LocalizedPageIntro({
  eyebrowKey,
  titleKey,
  summaryKey,
}: {
  eyebrowKey: string;
  titleKey: string;
  summaryKey?: string;
}) {
  const t = useT();

  return (
    <div className="px-1">
      <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">{t(eyebrowKey)}</p>
      <h1 className="mt-1 text-2xl font-semibold text-ink">{t(titleKey)}</h1>
      {summaryKey ? <p className="mt-2 text-sm text-[#596270]">{t(summaryKey)}</p> : null}
    </div>
  );
}
