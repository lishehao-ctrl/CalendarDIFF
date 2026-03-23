"use client";

import { PageHeader } from "@/components/page-header";
import { useT } from "@/lib/i18n/use-locale";

export function LocalizedPageHeader({
  eyebrowKey,
  titleKey,
  descriptionKey,
  badgeKey,
}: {
  eyebrowKey: string;
  titleKey: string;
  descriptionKey: string;
  badgeKey?: string;
}) {
  const t = useT();

  return (
    <PageHeader
      eyebrow={t(eyebrowKey)}
      title={t(titleKey)}
      description={t(descriptionKey)}
      badge={badgeKey ? t(badgeKey) : undefined}
    />
  );
}
