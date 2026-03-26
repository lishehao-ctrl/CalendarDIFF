"use client";

import { PageHeader } from "@/components/page-header";
import { useT } from "@/lib/i18n/use-locale";
import { usePageMetadata } from "@/lib/use-page-metadata";

export function LocalizedPageHeader({
  eyebrowKey,
  titleKey,
  descriptionKey,
  badgeKey,
  badgeTone,
  titleAs,
}: {
  eyebrowKey: string;
  titleKey: string;
  descriptionKey: string;
  badgeKey?: string;
  badgeTone?: string;
  titleAs?: "h1" | "h2";
}) {
  const t = useT();
  const title = t(titleKey);
  const description = t(descriptionKey);

  usePageMetadata(title, description);

  return (
    <PageHeader
      eyebrow={t(eyebrowKey)}
      title={title}
      description={description}
      badge={badgeKey ? t(badgeKey) : undefined}
      badgeTone={badgeTone}
      titleAs={titleAs}
    />
  );
}
