"use client";

import Link from "next/link";
import { ArrowRight, BellDot, GitCompareArrows, Link2, PencilLine } from "lucide-react";
import { AgentBriefCard } from "@/components/agent-brief-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ErrorState } from "@/components/data-states";
import { WorkbenchLoadingShell } from "@/components/workbench-loading-shell";
import { changesListCacheKey, changesSummaryCacheKey, getChangesSummary, listChanges } from "@/lib/api/changes";
import { getOnboardingStatus, onboardingStatusCacheKey } from "@/lib/api/onboarding";
import { listSources, sourceListCacheKey } from "@/lib/api/sources";
import { withBasePath } from "@/lib/demo-mode";
import { translate } from "@/lib/i18n/runtime";
import { buildOverviewSurface } from "@/lib/overview";
import { formatDateTime, summarizeChange } from "@/lib/presenters";
import { usePageMetadata } from "@/lib/use-page-metadata";
import { useResponsiveTier } from "@/lib/use-responsive-tier";
import type { ChangeItem, ChangesWorkbenchSummary, OnboardingStatus, SourceRow } from "@/lib/types";
import { useApiResource } from "@/lib/use-api-resource";
import { workbenchQueueRowClassName, workbenchSupportPanelClassName } from "@/lib/workbench-styles";

const cardIcons = {
  "needs-review": GitCompareArrows,
  "source-posture": BellDot,
  "naming-drift": Link2,
  fallbacks: PencilLine,
} as const;

export default function OverviewPage({ basePath = "" }: { basePath?: string }) {
  const { isMobile, isTabletPortrait, isTabletWide, isDesktop } = useResponsiveTier();
  const topPendingParams = {
    review_status: "pending" as const,
    review_bucket: "changes" as const,
    intake_phase: "replay" as const,
    limit: 3,
  };
  const summary = useApiResource<ChangesWorkbenchSummary>(() => getChangesSummary(), [], null, {
    cacheKey: changesSummaryCacheKey(),
  });
  const topPendingChanges = useApiResource<ChangeItem[]>(
    () => listChanges(topPendingParams),
    [],
    null,
    { cacheKey: changesListCacheKey(topPendingParams) },
  );
  const activeSources = useApiResource<SourceRow[]>(
    () => listSources({ status: "active" }),
    [],
    null,
    { cacheKey: sourceListCacheKey("active") },
  );
  const onboarding = useApiResource<OnboardingStatus>(() => getOnboardingStatus(), [], null, {
    cacheKey: onboardingStatusCacheKey(),
  });
  const surface = summary.data && onboarding.data && topPendingChanges.data
    ? buildOverviewSurface({
        summary: summary.data,
        topPendingChange: topPendingChanges.data[0] || null,
        onboarding: onboarding.data,
      })
    : null;

  usePageMetadata(surface?.hero.title || translate("shell.nav.overview.label"), surface?.hero.summary || translate("shell.nav.overview.description"));

  if (summary.loading || topPendingChanges.loading || onboarding.loading || activeSources.loading) {
    return <WorkbenchLoadingShell variant="overview" />;
  }

  const errorMessage = summary.error || topPendingChanges.error || onboarding.error || activeSources.error;
  if (errorMessage) {
    return <ErrorState message={`${translate("overview.loadFailed")} ${errorMessage}`} actionLabel={translate("overview.cards.sources.open")} actionHref={withBasePath(basePath, "/sources")} />;
  }

  if (!summary.data || !onboarding.data || !topPendingChanges.data || !activeSources.data) {
    return <ErrorState message={translate("overview.loadUnavailable")} />;
  }

  if (!surface) {
    return <ErrorState message={translate("overview.loadUnavailable")} />;
  }
  const posturePhase = summary.data.workspace_posture.phase;
  const recentChanges = topPendingChanges.data;
  const sourceAttentionRows = activeSources.data.filter((source) => source.source_recovery?.trust_state && source.source_recovery.trust_state !== "trusted");
  const sourcePostureCard = surface.cards.find((card) => card.key === "source-posture");
  const familiesCard = surface.cards.find((card) => card.key === "naming-drift");
  const manualCard = surface.cards.find((card) => card.key === "fallbacks");
  const showReplayList = posturePhase === "monitoring_live";

  const changesSummaryCard = (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("overview.cards.changes.eyebrow")}</p>
          <h2 className="mt-2 text-lg font-semibold text-ink">{translate("overview.cards.changes.reviewTitle")}</h2>
        </div>
        <Badge tone={surface.cards[0].tone}>{surface.cards[0].metric}</Badge>
      </div>
      <div className="mt-4 space-y-3">
        {showReplayList && recentChanges.length > 0 ? (
          recentChanges.map((change) => {
            const summary = summarizeChange(change);
            return (
              <Link
                key={change.id}
                href={withBasePath(basePath, `/changes?focus=${change.id}`)}
                className={workbenchQueueRowClassName({
                  className: "flex items-center justify-between px-4 py-3",
                })}
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink">{summary.title}</p>
                  <p className="mt-1 text-xs text-[#6d7885]">{formatDateTime(change.detected_at)}</p>
                </div>
                <ArrowRight className="h-4 w-4 text-[#6d7885]" />
              </Link>
            );
          })
        ) : (
          <>
            <p className="text-sm text-[#596270]">{surface.cards[0].summary}</p>
            {recentChanges.length > 0 ? (
              <div className="pt-1">
                <Link href={withBasePath(basePath, surface.cards[0].ctaHref)}>
                  <Button size="sm" variant="ghost">{surface.cards[0].ctaLabel}</Button>
                </Link>
              </div>
            ) : null}
          </>
        )}
      </div>
    </Card>
  );

  const sourceSummaryCard = sourcePostureCard ? (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-[1rem] bg-[rgba(20,32,44,0.06)] text-ink">
            <BellDot className="h-4 w-4" />
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{sourcePostureCard.eyebrow}</p>
            <h3 className="mt-1 text-base font-semibold text-ink">{sourcePostureCard.title}</h3>
          </div>
        </div>
        <Badge tone={sourcePostureCard.tone}>{sourcePostureCard.metric}</Badge>
      </div>
      <p className="mt-3 text-sm leading-6 text-[#596270]">{sourcePostureCard.summary}</p>
      {sourceAttentionRows.length > 0 ? (
        <div className="mt-3 space-y-2">
          {sourceAttentionRows.slice(0, 2).map((source) => (
            <div key={source.source_id} className={workbenchSupportPanelClassName("default", "px-3 py-2 text-sm text-[#314051]")}>
              <p className="font-medium text-ink">{source.display_name || source.provider}</p>
              <p className="mt-1 text-xs text-[#6d7885]">{source.source_recovery?.impact_summary || source.last_error_message}</p>
            </div>
          ))}
        </div>
      ) : null}
      <div className="mt-3">
        <Link href={withBasePath(basePath, sourcePostureCard.ctaHref)}>
          <Button size="sm" variant="ghost">{sourcePostureCard.ctaLabel}</Button>
        </Link>
      </div>
    </Card>
  ) : null;

  const supportSummaryCards = [familiesCard, manualCard].filter(Boolean).map((card) => {
    if (!card) return null;
    const Icon = card.key === "naming-drift" ? Link2 : PencilLine;
    return (
      <Card key={card.key} className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-[1rem] bg-[rgba(20,32,44,0.06)] text-ink">
              <Icon className="h-4 w-4" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{card.eyebrow}</p>
              <h3 className="mt-1 text-base font-semibold text-ink">{card.title}</h3>
            </div>
          </div>
          <Badge tone={card.tone}>{card.metric}</Badge>
        </div>
        <p className="mt-3 text-sm leading-6 text-[#596270]">{card.summary}</p>
        <div className="mt-3">
          <Link href={withBasePath(basePath, card.ctaHref)}>
            <Button size="sm" variant="ghost">{card.ctaLabel}</Button>
          </Link>
        </div>
      </Card>
    );
  });

  const nextStepCard = (
    <Card className="p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-2xl">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.brief.ready")}</p>
          <h2 className="mt-2 text-xl font-semibold text-ink">{surface.hero.ctaLabel}</h2>
          <p className="mt-2 text-sm leading-6 text-[#596270]">{surface.hero.ctaReason}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {surface.hero.meta.map((item) => (
            <Badge key={item} tone="info">{item}</Badge>
          ))}
        </div>
      </div>
      {surface.hero.progressLabel && typeof surface.hero.progressPercent === "number" ? (
        <div className="mt-4 max-w-xl space-y-2">
          <div className="flex items-center justify-between gap-3 text-sm text-[#596270]">
            <span>{surface.hero.progressLabel}</span>
            <span>{surface.hero.progressPercent}%</span>
          </div>
          <div className="h-2 rounded-full bg-[rgba(20,32,44,0.08)]">
            <div
              className="h-2 rounded-full bg-cobalt transition-all duration-500"
              style={{ width: `${Math.min(Math.max(surface.hero.progressPercent, 0), 100)}%` }}
            />
          </div>
        </div>
      ) : null}
      <div className="mt-4">
        <Link href={withBasePath(basePath, surface.hero.ctaHref)}>
          <Button size="sm">
            {surface.hero.ctaLabel}
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </Link>
      </div>
    </Card>
  );

  const onboardingCard = onboarding.data.stage !== "ready" ? (
    <Card className="p-4">
      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("onboarding.introEyebrow")}</p>
      <h3 className="mt-2 text-base font-semibold text-ink">{translate("onboarding.introTitle")}</h3>
      <p className="mt-2 text-sm leading-6 text-[#596270]">{onboarding.data.message || translate("onboarding.statusUnavailable")}</p>
    </Card>
  ) : null;

  const summaryCardGrid = (
    <div className={isMobile ? "space-y-4" : "grid gap-4 md:grid-cols-2"}>
      {changesSummaryCard}
      {sourceSummaryCard}
      {supportSummaryCards}
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="px-1">
        <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">{surface.hero.eyebrow}</p>
        <h1 className="mt-1 text-2xl font-semibold text-ink">{surface.hero.title}</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-[#596270]">{surface.hero.summary}</p>
      </div>

      {isDesktop ? (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_340px]">
          <div className="space-y-5">
            {nextStepCard}
            <div className="grid gap-5 xl:items-start xl:grid-cols-[minmax(0,1fr)_320px]">
              {changesSummaryCard}
              <div className="space-y-4">
                {sourceSummaryCard}
                {supportSummaryCards}
              </div>
            </div>
          </div>
          <div className="space-y-4">
            <AgentBriefCard basePath={basePath} />
            {onboardingCard}
          </div>
        </div>
      ) : isTabletWide ? (
        <div className="space-y-5">
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1.2fr)_320px]">
            {nextStepCard}
            <div className="space-y-4">
              <AgentBriefCard basePath={basePath} />
              {onboardingCard}
            </div>
          </div>
          {summaryCardGrid}
        </div>
      ) : isTabletPortrait ? (
        <div className="space-y-5">
          {nextStepCard}
          {summaryCardGrid}
          <AgentBriefCard basePath={basePath} />
          {onboardingCard}
        </div>
      ) : (
        <div className="space-y-5">
          {nextStepCard}
          <AgentBriefCard basePath={basePath} />
          {summaryCardGrid}
          {onboardingCard}
        </div>
      )}
    </div>
  );
}
