"use client";

import Link from "next/link";
import { ArrowRight, BellDot, GitCompareArrows, Link2, PencilLine } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/data-states";
import { changesListCacheKey, changesSummaryCacheKey, getChangesSummary, listChanges } from "@/lib/api/changes";
import { getOnboardingStatus, onboardingStatusCacheKey } from "@/lib/api/onboarding";
import { withBasePath } from "@/lib/demo-mode";
import { buildOverviewSurface } from "@/lib/overview";
import type { ChangeItem, ChangesWorkbenchSummary, OnboardingStatus } from "@/lib/types";
import { useApiResource } from "@/lib/use-api-resource";

const cardIcons = {
  "needs-review": GitCompareArrows,
  "source-posture": BellDot,
  "naming-drift": Link2,
  fallbacks: PencilLine,
} as const;

export default function OverviewPage({ basePath = "" }: { basePath?: string }) {
  const topPendingParams = {
    review_status: "pending" as const,
    review_bucket: "changes" as const,
    intake_phase: "replay" as const,
    limit: 1,
  };
  const summary = useApiResource<ChangesWorkbenchSummary>(() => getChangesSummary(), [], null, {
    cacheKey: changesSummaryCacheKey(),
  });
  const topPendingChange = useApiResource<ChangeItem[]>(
    () => listChanges(topPendingParams),
    [],
    null,
    { cacheKey: changesListCacheKey(topPendingParams) },
  );
  const onboarding = useApiResource<OnboardingStatus>(() => getOnboardingStatus(), [], null, {
    cacheKey: onboardingStatusCacheKey(),
  });

  if (summary.loading || topPendingChange.loading || onboarding.loading) {
    return <LoadingState label="overview" />;
  }

  const errorMessage = summary.error || topPendingChange.error || onboarding.error;
  if (errorMessage) {
    return <ErrorState message={`Overview could not assemble the current workspace state. ${errorMessage}`} actionLabel="Open Sources" actionHref={withBasePath(basePath, "/sources")} />;
  }

  if (!summary.data || !onboarding.data || !topPendingChange.data) {
    return <ErrorState message="Overview could not assemble the current workspace state." />;
  }

  const surface = buildOverviewSurface({
    summary: summary.data,
    topPendingChange: topPendingChange.data[0] || null,
    onboarding: onboarding.data,
  });

  return (
    <div className="space-y-5">
      <Card className="animate-surface-enter relative overflow-hidden p-6 md:p-7">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.14),transparent_36%),radial-gradient(circle_at_82%_18%,rgba(215,90,45,0.12),transparent_26%)]" />
        <div className="relative max-w-3xl">
          <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">{surface.hero.eyebrow}</p>
          <h1 className="mt-3 text-3xl font-semibold text-ink">{surface.hero.title}</h1>
          <p className="mt-3 max-w-2xl text-sm leading-7 text-[#596270]">{surface.hero.summary}</p>
          {surface.hero.progressLabel && typeof surface.hero.progressPercent === "number" ? (
            <div className="mt-5 max-w-xl space-y-2">
              <div className="flex items-center justify-between gap-3 text-sm text-[#596270]">
                <span>{surface.hero.progressLabel}</span>
                <span>{surface.hero.progressPercent}%</span>
              </div>
              <div className="h-2 rounded-full bg-white/60">
                <div
                  className="h-2 rounded-full bg-cobalt transition-all duration-500"
                  style={{ width: `${Math.min(Math.max(surface.hero.progressPercent, 0), 100)}%` }}
                />
              </div>
            </div>
          ) : null}
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <Link href={withBasePath(basePath, surface.hero.ctaHref)}>
              <Button>
                {surface.hero.ctaLabel}
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </Link>
          </div>
        </div>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        {surface.cards.map((card, index) => {
          const Icon = cardIcons[card.key];
          return (
            <Card
              key={card.key}
              className="animate-surface-enter interactive-lift p-5 transition-all duration-300 hover:-translate-y-0.5 hover:bg-white"
              style={{ transitionDelay: `${index * 40}ms` }}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(20,32,44,0.06)] text-ink">
                    <Icon className="h-5 w-5" />
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{card.eyebrow}</p>
                    <h2 className="mt-2 text-xl font-semibold text-ink">{card.title}</h2>
                  </div>
                </div>
                <Badge tone={card.tone}>{card.metric}</Badge>
              </div>
              <p className="mt-4 text-sm leading-7 text-[#596270]">{card.summary}</p>
              <div className="mt-5">
                <Link href={withBasePath(basePath, card.ctaHref)}>
                  <Button>
                    {card.ctaLabel}
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                </Link>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
