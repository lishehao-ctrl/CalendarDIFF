import type { ChangeItem, ChangesWorkbenchSummary, OnboardingStatus } from "@/lib/types";
import { translate } from "@/lib/i18n/runtime";
import { formatDateTime, sourceDescriptor, summarizeChange } from "@/lib/presenters";

export type OverviewCardVM = {
  key: "needs-review" | "source-posture";
  title: string;
  eyebrow: string;
  metric: string;
  summary: string;
  ctaLabel: string;
  ctaHref: string;
  tone: "pending" | "approved" | "info";
};

export type OverviewHeroVM = {
  eyebrow: string;
  title: string;
  summary: string;
  ctaLabel: string;
  ctaHref: string;
  ctaReason: string;
  progressLabel?: string;
  progressPercent?: number;
  meta: string[];
};

export type OverviewSurfaceVM = {
  hero: OverviewHeroVM;
  cards: OverviewCardVM[];
};

function surfaceHref(surface: OverviewHeroVM["ctaHref"] extends never ? never : string) {
  switch (surface) {
    case "sources":
      return "/sources";
    case "initial_review":
      return "/changes?bucket=initial_review";
    case "changes":
      return "/changes";
    default:
      return "/overview";
  }
}

function buildHero(summary: ChangesWorkbenchSummary): OverviewHeroVM {
  const { workspace_posture: posture } = summary;
  const nextActionHref = surfaceHref(posture.next_action.lane);
  const initialReview = posture.initial_review;
  const monitoring = posture.monitoring;

  switch (posture.phase) {
    case "baseline_import":
      return {
        eyebrow: translate("overview.heroEyebrow"),
        title: translate("overview.phase.baselineImportTitle"),
        summary: translate("overview.phase.baselineImportSummary"),
        ctaLabel: posture.next_action.label,
        ctaHref: nextActionHref,
        ctaReason: posture.next_action.reason,
        meta: [
          translate("overview.phase.activeSources", { count: summary.sources.active_count }),
          initialReview.total_count > 0
            ? translate("overview.phase.baselinePrepared", { count: initialReview.total_count })
            : translate("overview.phase.reviewOpensAfterImport"),
        ],
      };
    case "initial_review":
      return {
        eyebrow: translate("overview.heroEyebrow"),
        title: translate("overview.phase.initialReviewTitle"),
        summary:
          initialReview.pending_count === 1
            ? translate("overview.phase.initialReviewSummaryOne")
            : translate("overview.phase.initialReviewSummaryMany", { count: initialReview.pending_count }),
        ctaLabel: posture.next_action.label,
        ctaHref: nextActionHref,
        ctaReason: posture.next_action.reason,
        progressLabel: translate("overview.phase.reviewedOfTotal", {
          reviewed: initialReview.reviewed_count,
          total: initialReview.total_count,
        }),
        progressPercent: initialReview.completion_percent,
        meta: [
          translate("overview.phase.pending", { count: initialReview.pending_count }),
          initialReview.completed_at
            ? translate("overview.phase.completedAt", { time: formatDateTime(initialReview.completed_at) })
            : translate("overview.phase.monitoringStartsAfterReview"),
        ],
      };
    case "monitoring_live":
      return {
        eyebrow: translate("overview.heroEyebrow"),
        title: translate("overview.phase.monitoringLiveTitle"),
        summary: translate("overview.phase.monitoringLiveSummary"),
        ctaLabel: posture.next_action.label,
        ctaHref: nextActionHref,
        ctaReason: posture.next_action.reason,
        meta: [
          monitoring.live_since
            ? translate("overview.phase.liveSince", { time: formatDateTime(monitoring.live_since) })
            : translate("overview.phase.liveMonitoringActive"),
          translate("overview.phase.activeSources", { count: monitoring.active_source_count }),
        ],
      };
    case "attention_required":
    default:
      return {
        eyebrow: translate("overview.heroEyebrow"),
        title: translate("overview.phase.attentionRequiredTitle"),
        summary: translate("overview.phase.attentionRequiredSummary"),
        ctaLabel: posture.next_action.label,
        ctaHref: nextActionHref,
        ctaReason: posture.next_action.reason,
        meta: [
          translate("overview.phase.attentionSources", { count: summary.sources.attention_count }),
          translate("overview.phase.replayChanges", { count: summary.changes_pending }),
        ],
      };
  }
}

export function buildOverviewSurface(params: {
  summary: ChangesWorkbenchSummary;
  topPendingChange: ChangeItem | null;
  onboarding: OnboardingStatus;
}): OverviewSurfaceVM {
  const { summary, topPendingChange, onboarding } = params;
  const posture = summary.workspace_posture;
  const initialReview = posture.initial_review;

  const replayReviewSummary = topPendingChange
    ? translate("overview.cards.changes.topPending", {
        title: summarizeChange(topPendingChange).title,
        source: topPendingChange.primary_source
          ? sourceDescriptor(topPendingChange.primary_source)
          : translate("changes.workspace.attachedEvidence"),
      })
    : summary.changes_pending > 0
      ? translate("overview.cards.changes.replayWaiting", { count: summary.changes_pending })
      : translate("overview.cards.changes.noReplayWaiting");

  const needsReviewCard: OverviewCardVM =
    initialReview.pending_count > 0
      ? {
          key: "needs-review",
          eyebrow: translate("overview.cards.changes.eyebrow"),
          title: translate("overview.cards.changes.queueTitle"),
          metric: `${summary.changes_pending}`,
          summary:
            summary.changes_pending > 0
              ? translate("overview.cards.changes.replayWaiting", { count: summary.changes_pending })
              : translate("overview.cards.changes.quiet"),
          ctaLabel: translate("overview.cards.changes.open"),
          ctaHref: "/changes",
          tone: summary.changes_pending > 0 ? "pending" : "info",
        }
      : {
          key: "needs-review",
          eyebrow: translate("overview.cards.changes.eyebrow"),
          title: translate("overview.cards.changes.reviewTitle"),
          metric: `${summary.changes_pending}`,
          summary: replayReviewSummary,
          ctaLabel: translate("overview.cards.changes.open"),
          ctaHref: "/changes",
          tone: summary.changes_pending > 0 ? "pending" : "approved",
        };

  const sourceSummary =
    onboarding.stage !== "ready"
      ? onboarding.message || translate("overview.cards.sources.setupFirst")
      : summary.sources.attention_count > 0
        ? summary.sources.message
        : posture.phase === "baseline_import"
          ? translate("overview.cards.sources.baselineRunning")
          : translate("overview.cards.sources.steadyState");

  return {
    hero: buildHero(summary),
    cards: [
      needsReviewCard,
      {
        key: "source-posture",
        eyebrow: translate("overview.cards.sources.eyebrow"),
        title: translate("overview.cards.sources.title"),
        metric: `${summary.sources.attention_count}`,
        summary: sourceSummary,
        ctaLabel: translate("overview.cards.sources.open"),
        ctaHref: "/sources",
        tone: summary.sources.attention_count > 0 || onboarding.stage !== "ready" ? "pending" : "approved",
      },
    ],
  };
}
