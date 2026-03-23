"use client";

import { LegalPage } from "@/components/legal-page";
import { useT } from "@/lib/i18n/use-locale";

type LegalSection = {
  title: string;
  body: readonly string[];
};

export function LocalizedLegalPage({
  kind,
  sections,
}: {
  kind: "privacy" | "terms";
  sections: readonly LegalSection[];
}) {
  const t = useT();

  return (
    <LegalPage
      eyebrow={t(`legal.${kind}.eyebrow`)}
      title={t(`legal.${kind}.title`)}
      summary={t(`legal.${kind}.summary`)}
      updatedAt={t(`legal.${kind}.updatedAt`)}
      sections={sections}
    />
  );
}
