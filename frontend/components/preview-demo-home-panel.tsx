"use client";

import Link from "next/link";
import { ArrowRight, BellDot, GitCompareArrows, Settings2, Sparkles, Wand2 } from "lucide-react";
import OverviewPage from "@/components/overview-page-client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { LocalizedPageIntro } from "@/components/localized-page-intro";
import { translate } from "@/lib/i18n/runtime";
import { workbenchSupportPanelClassName } from "@/lib/workbench-styles";

const demoCards = [
  {
    key: "changes",
    href: "/preview/changes",
    icon: GitCompareArrows,
    titleKey: "previewDemo.cards.changes.title",
    summaryKey: "previewDemo.cards.changes.summary",
    ctaKey: "previewDemo.cards.changes.cta",
  },
  {
    key: "sources",
    href: "/preview/sources/2",
    icon: BellDot,
    titleKey: "previewDemo.cards.sources.title",
    summaryKey: "previewDemo.cards.sources.summary",
    ctaKey: "previewDemo.cards.sources.cta",
  },
  {
    key: "assistant",
    href: "/preview/agent",
    icon: Sparkles,
    titleKey: "previewDemo.cards.assistant.title",
    summaryKey: "previewDemo.cards.assistant.summary",
    ctaKey: "previewDemo.cards.assistant.cta",
  },
  {
    key: "settings",
    href: "/preview/settings",
    icon: Settings2,
    titleKey: "previewDemo.cards.settings.title",
    summaryKey: "previewDemo.cards.settings.summary",
    ctaKey: "previewDemo.cards.settings.cta",
  },
] as const;

export function PreviewDemoHomePanel() {
  return (
    <div className="space-y-5">
      <LocalizedPageIntro
        eyebrowKey="previewDemo.home.eyebrow"
        titleKey="previewDemo.home.title"
        summaryKey="previewDemo.home.summary"
      />

      <Card className="animate-surface-enter overflow-hidden border-cobalt/15 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.12),transparent_38%),linear-gradient(180deg,rgba(255,255,255,0.98),rgba(246,249,255,0.95))] p-5 md:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("previewDemo.path.eyebrow")}</p>
            <h2 className="mt-2 text-xl font-semibold text-ink">{translate("previewDemo.path.title")}</h2>
            <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("previewDemo.path.summary")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="info">{translate("previewDemo.badge")}</Badge>
            <Button asChild size="sm">
              <Link href="/preview/changes">
                {translate("previewDemo.path.primaryCta")}
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2 text-xs text-[#6d7885]">
          <span className="rounded-full border border-line/70 bg-white/72 px-3 py-1.5">{translate("previewDemo.path.step1")}</span>
          <span className="rounded-full border border-line/70 bg-white/72 px-3 py-1.5">{translate("previewDemo.path.step2")}</span>
          <span className="rounded-full border border-line/70 bg-white/72 px-3 py-1.5">{translate("previewDemo.path.step3")}</span>
          <span className="rounded-full border border-line/70 bg-white/72 px-3 py-1.5">{translate("previewDemo.path.step4")}</span>
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {demoCards.map((card, index) => {
          const Icon = card.icon;
          return (
            <Card key={card.key} className={`animate-surface-enter p-4 ${index === 0 ? "animate-surface-delay-1" : index === 1 ? "animate-surface-delay-2" : "animate-surface-delay-3"}`}>
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[rgba(20,32,44,0.06)] text-ink">
                <Icon className="h-4 w-4" />
              </div>
              <h3 className="mt-4 text-base font-semibold text-ink">{translate(card.titleKey)}</h3>
              <p className="mt-2 text-sm leading-6 text-[#596270]">{translate(card.summaryKey)}</p>
              <div className="mt-4">
                <Button asChild size="sm" variant="soft">
                  <Link href={card.href}>{translate(card.ctaKey)}</Link>
                </Button>
              </div>
            </Card>
          );
        })}
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_320px]">
        <Card className="animate-surface-enter p-4">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("previewDemo.snapshot.eyebrow")}</p>
          <h3 className="mt-2 text-base font-semibold text-ink">{translate("previewDemo.snapshot.title")}</h3>
          <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("previewDemo.snapshot.summary")}</p>
        </Card>
        <div className={workbenchSupportPanelClassName("info", "animate-surface-enter p-4")}>
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[rgba(31,94,255,0.1)] text-cobalt">
              <Wand2 className="h-4 w-4" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("previewDemo.tip.eyebrow")}</p>
              <p className="mt-2 text-sm leading-6 text-[#314051]">{translate("previewDemo.tip.summary")}</p>
            </div>
          </div>
        </div>
      </div>

      <OverviewPage basePath="/preview" hidePageIntro suppressPageMetadata />
    </div>
  );
}
