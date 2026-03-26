"use client";

import { useEffect } from "react";
import { LegalPage } from "@/components/legal-page";
import { useT } from "@/lib/i18n/use-locale";
import { translateArray } from "@/lib/i18n/runtime";

type LegalSection = {
  title: string;
  body: readonly string[];
};

export function LocalizedLegalPage({
  kind,
}: {
  kind: "privacy" | "terms";
}) {
  const t = useT();
  const sections = translateArray<LegalSection>(`legal.${kind}.sections`);
  const title = t(`legal.${kind}.title`);
  const summary = t(`legal.${kind}.summary`);

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }
    document.title = `${title} | CalendarDIFF`;
    const descriptionTag = document.querySelector('meta[name="description"]');
    if (descriptionTag) {
      descriptionTag.setAttribute("content", summary);
    }
  }, [summary, title]);

  return (
    <LegalPage
      eyebrow={t(`legal.${kind}.eyebrow`)}
      title={title}
      summary={summary}
      updatedAt={t(`legal.${kind}.updatedAt`)}
      sections={sections}
    />
  );
}
