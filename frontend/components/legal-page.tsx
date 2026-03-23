"use client";

import Link from "next/link";
import { Card } from "@/components/ui/card";
import { useT } from "@/lib/i18n/use-locale";

type LegalSection = {
  title: string;
  body: readonly string[];
};

export function LegalPage({
  eyebrow,
  title,
  summary,
  updatedAt,
  sections
}: {
  eyebrow: string;
  title: string;
  summary: string;
  updatedAt: string;
  sections: readonly LegalSection[];
}) {
  const t = useT();

  return (
    <div className="min-h-screen bg-transparent px-4 py-8 md:px-8">
      <div className="mx-auto flex min-h-[80vh] max-w-6xl items-center justify-center">
        <div className="grid w-full gap-6 lg:grid-cols-[0.9fr_1.1fr]">
          <Card className="relative overflow-hidden p-8 md:p-10">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.16),transparent_42%),radial-gradient(circle_at_80%_20%,rgba(215,90,45,0.12),transparent_30%)]" />
            <div className="relative space-y-6">
              <div>
                <p className="text-xs uppercase tracking-[0.24em] text-[#6d7885]">{t("legal.brand")}</p>
                <h1 className="mt-4 text-4xl font-semibold leading-tight text-ink">{title}</h1>
                <p className="mt-5 max-w-xl text-sm leading-7 text-[#596270]">{summary}</p>
              </div>
              <div className="rounded-[1.15rem] border border-line/80 bg-white/55 p-4 text-sm text-[#314051]">
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{t("legal.whatThisCovers")}</p>
                <ul className="mt-3 space-y-2 leading-6">
                  {(["0", "1", "2"] as const).map((index) => (
                    <li key={index}>{t(`legal.coverItems.${index}`)}</li>
                  ))}
                </ul>
              </div>
              <div className="flex flex-wrap gap-3 text-sm text-[#596270]">
                <Link className="font-medium text-cobalt" href="/login">
                  {t("legal.backToSignIn")}
                </Link>
                <span aria-hidden="true">•</span>
                <Link className="font-medium text-cobalt" href="/register">
                  {t("legal.createAccount")}
                </Link>
              </div>
            </div>
          </Card>
          <Card className="p-8 md:p-10">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line/80 pb-5">
              <div>
                <p className="text-xs uppercase tracking-[0.24em] text-[#6d7885]">{eyebrow}</p>
                <h2 className="mt-3 text-3xl font-semibold text-ink">{title}</h2>
              </div>
              <div className="rounded-full border border-line/80 bg-white/65 px-4 py-2 text-xs uppercase tracking-[0.18em] text-[#6d7885]">
                {t("legal.updated", { date: updatedAt })}
              </div>
            </div>
            <div className="mt-6 space-y-6 text-sm leading-7 text-[#314051]">
              {sections.map((section) => (
                <section key={section.title} className="space-y-3">
                  <h3 className="text-xl font-semibold text-ink">{section.title}</h3>
                  <div className="space-y-3">
                    {section.body.map((paragraph) => (
                      <p key={paragraph}>{paragraph}</p>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
