"use client";

import Link from "next/link";
import { ArrowRight, BellDot, GitCompareArrows, Link2, PencilLine } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/data-states";
import { getChangesSummary, listChanges } from "@/lib/api/changes";
import { getOnboardingStatus } from "@/lib/api/onboarding";
import { listSources } from "@/lib/api/sources";
import { withBasePath } from "@/lib/demo-mode";
import { buildInitialReviewSummary } from "@/lib/import-review";
import { buildOverviewCards } from "@/lib/overview";
import type { ChangesWorkbenchSummary, OnboardingStatus, ChangeItem, SourceRow } from "@/lib/types";
import { useSourceObservabilityMap } from "@/lib/use-source-observability-map";
import { useApiResource } from "@/lib/use-api-resource";

const cardIcons = {
  "needs-review": GitCompareArrows,
  "source-posture": BellDot,
  "naming-drift": Link2,
  fallbacks: PencilLine,
} as const;

export default function OverviewPage({ basePath = "" }: { basePath?: string }) {
  const summary = useApiResource<ChangesWorkbenchSummary>(() => getChangesSummary(), []);
  const topPendingChange = useApiResource<ChangeItem[]>(
    () => listChanges({ review_status: "pending", review_bucket: "changes", intake_phase: "replay", limit: 1 }),
    [],
  );
  const onboarding = useApiResource<OnboardingStatus>(() => getOnboardingStatus(), []);
  const sources = useApiResource<SourceRow[]>(() => listSources({ status: "active" }), []);
  const observability = useSourceObservabilityMap(sources.data || []);

  if (summary.loading || topPendingChange.loading || onboarding.loading || sources.loading || observability.loading) {
    return <LoadingState label="overview" />;
  }

  const errorMessage =
    summary.error ||
    topPendingChange.error ||
    onboarding.error ||
    sources.error ||
    observability.error;
  if (errorMessage) {
    return <ErrorState message={`Overview could not assemble the current workspace state. ${errorMessage}`} actionLabel="Open Sources" actionHref={withBasePath(basePath, "/sources")} />;
  }

  if (!summary.data || !onboarding.data || !topPendingChange.data || !sources.data) {
    return <ErrorState message="Overview could not assemble the current workspace state." />;
  }

  const initialReview = buildInitialReviewSummary({
    sources: sources.data,
    observabilityMap: observability.data,
    workbenchSummary: summary.data,
  });

  const cards = buildOverviewCards({
    summary: summary.data,
    topPendingChange: topPendingChange.data[0] || null,
    onboarding: onboarding.data,
    initialReview,
  });

  return (
    <div className="space-y-5">
      <Card className="animate-surface-enter relative overflow-hidden p-6 md:p-7">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.14),transparent_36%),radial-gradient(circle_at_82%_18%,rgba(215,90,45,0.12),transparent_26%)]" />
        <div className="relative max-w-3xl">
          <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">Overview</p>
          <h1 className="mt-3 text-3xl font-semibold text-ink">Route attention to the right lane.</h1>
          <p className="mt-3 text-sm text-[#596270]">Four cards. One next step.</p>
        </div>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        {cards.map((card, index) => {
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
