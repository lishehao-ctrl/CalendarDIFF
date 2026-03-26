"use client";

import { useT } from "@/lib/i18n/use-locale";
import { usePageMetadata } from "@/lib/use-page-metadata";

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
  const title = t(titleKey);
  const summary = summaryKey ? t(summaryKey) : null;

  usePageMetadata(title, summary);

  return (
    <div className="px-1">
      <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">{t(eyebrowKey)}</p>
      <h1 className="mt-1 text-2xl font-semibold text-ink">{title}</h1>
      {summary ? <p className="mt-2 text-sm text-[#596270]">{summary}</p> : null}
    </div>
  );
}
