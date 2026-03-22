import type { ChangeItem, ChangesWorkbenchSummary, OnboardingStatus } from "@/lib/types";
import { formatDateTime, sourceDescriptor, summarizeChange } from "@/lib/presenters";

export type OverviewCardVM = {
  key: "needs-review" | "source-posture" | "naming-drift" | "fallbacks";
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

function laneHref(lane: OverviewHeroVM["ctaHref"] extends never ? never : string) {
  switch (lane) {
    case "sources":
      return "/sources";
    case "initial_review":
      return "/initial-review";
    case "changes":
      return "/changes";
    case "families":
      return "/families";
    case "manual":
      return "/manual";
    default:
      return "/overview";
  }
}

function buildHero(summary: ChangesWorkbenchSummary): OverviewHeroVM {
  const { workspace_posture: posture } = summary;
  const nextActionHref = laneHref(posture.next_action.lane);
  const initialReview = posture.initial_review;
  const monitoring = posture.monitoring;

  switch (posture.phase) {
    case "baseline_import":
      return {
        eyebrow: "Workspace posture",
        title: "Building your baseline",
        summary: "CalendarDIFF is still assembling the first import. Use Sources to confirm what landed and whether any source needs attention before review begins.",
        ctaLabel: posture.next_action.label,
        ctaHref: nextActionHref,
        ctaReason: posture.next_action.reason,
        meta: [
          `${summary.sources.active_count} active source${summary.sources.active_count === 1 ? "" : "s"}`,
          initialReview.total_count > 0 ? `${initialReview.total_count} baseline item${initialReview.total_count === 1 ? "" : "s"} prepared` : "Review opens after import finishes",
        ],
      };
    case "initial_review":
      return {
        eyebrow: "Workspace posture",
        title: "Initial Review in progress",
        summary:
          initialReview.pending_count === 1
            ? "1 baseline item still needs a decision before monitoring is fully live."
            : `${initialReview.pending_count} baseline items still need decisions before monitoring is fully live.`,
        ctaLabel: posture.next_action.label,
        ctaHref: nextActionHref,
        ctaReason: posture.next_action.reason,
        progressLabel: `${initialReview.reviewed_count} reviewed / ${initialReview.total_count} total`,
        progressPercent: initialReview.completion_percent,
        meta: [
          `${initialReview.pending_count} pending`,
          initialReview.completed_at ? `Completed ${formatDateTime(initialReview.completed_at)}` : "Monitoring starts after this review closes",
        ],
      };
    case "monitoring_live":
      return {
        eyebrow: "Workspace posture",
        title: "Monitoring is live",
        summary: "The initial baseline is complete. CalendarDIFF is now watching your connected sources for new changes that need replay review.",
        ctaLabel: posture.next_action.label,
        ctaHref: nextActionHref,
        ctaReason: posture.next_action.reason,
        meta: [
          monitoring.live_since ? `Live since ${formatDateTime(monitoring.live_since)}` : "Live monitoring is active",
          `${monitoring.active_source_count} active source${monitoring.active_source_count === 1 ? "" : "s"}`,
        ],
      };
    case "attention_required":
    default:
      return {
        eyebrow: "Workspace posture",
        title: "Attention required",
        summary: "A source or review lane needs attention before the workspace is fully trustworthy. Start with the recommended lane below.",
        ctaLabel: posture.next_action.label,
        ctaHref: nextActionHref,
        ctaReason: posture.next_action.reason,
        meta: [
          `${summary.sources.attention_count} source${summary.sources.attention_count === 1 ? "" : "s"} need attention`,
          `${summary.changes_pending} replay change${summary.changes_pending === 1 ? "" : "s"} waiting`,
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
    ? `${summarizeChange(topPendingChange).title} is waiting from ${topPendingChange.primary_source ? sourceDescriptor(topPendingChange.primary_source) : "attached evidence"}.`
    : summary.changes_pending > 0
      ? `${summary.changes_pending} replay change${summary.changes_pending === 1 ? "" : "s"} are waiting for review.`
      : "No replay changes are waiting right now.";

  const needsReviewCard: OverviewCardVM =
    initialReview.pending_count > 0
      ? {
          key: "needs-review",
          eyebrow: "Changes",
          title: "Changes queue",
          metric: `${summary.changes_pending}`,
          summary:
            summary.changes_pending > 0
              ? `${summary.changes_pending} replay change${summary.changes_pending === 1 ? "" : "s"} are waiting in Changes.`
              : "Changes is quiet right now.",
          ctaLabel: "Open Changes",
          ctaHref: "/changes",
          tone: summary.changes_pending > 0 ? "pending" : "info",
        }
      : {
          key: "needs-review",
          eyebrow: "Changes",
          title: "Review live changes",
          metric: `${summary.changes_pending}`,
          summary: replayReviewSummary,
          ctaLabel: "Open Changes",
          ctaHref: "/changes",
          tone: summary.changes_pending > 0 ? "pending" : "approved",
        };

  const sourceSummary =
    onboarding.stage !== "ready"
      ? onboarding.message || "Complete source setup before trusting intake."
      : summary.sources.attention_count > 0
        ? summary.sources.message
        : posture.phase === "baseline_import"
          ? "Sources are still building the first baseline."
          : "Connected sources are in steady-state monitoring.";

  const namingSummary = summary.families.pending_raw_type_suggestions > 0
    ? `${summary.families.pending_raw_type_suggestions} suggestion${summary.families.pending_raw_type_suggestions === 1 ? "" : "s"} are waiting in Families.`
    : summary.families.last_error
      ? `Families needs attention. ${summary.families.last_error}`
      : "No naming drift is waiting right now.";

  const fallbackSummary = summary.manual.active_event_count > 0
    ? `${summary.manual.active_event_count} manual fallback${summary.manual.active_event_count === 1 ? "" : "s"} are active.`
    : "No manual fallback work is open.";

  return {
    hero: buildHero(summary),
    cards: [
      needsReviewCard,
      {
        key: "source-posture",
        eyebrow: "Source Posture",
        title: "Check source trust",
        metric: `${summary.sources.attention_count}`,
        summary: sourceSummary,
        ctaLabel: "Open Sources",
        ctaHref: "/sources",
        tone: summary.sources.attention_count > 0 || onboarding.stage !== "ready" ? "pending" : "approved",
      },
      {
        key: "naming-drift",
        eyebrow: "Families",
        title: "Resolve naming drift",
        metric: `${summary.families.pending_raw_type_suggestions}`,
        summary: namingSummary,
        ctaLabel: "Open Families",
        ctaHref: "/families",
        tone: summary.families.pending_raw_type_suggestions > 0 ? "pending" : "info",
      },
      {
        key: "fallbacks",
        eyebrow: "Manual",
        title: "Clear fallback work",
        metric: `${summary.manual.active_event_count}`,
        summary: fallbackSummary,
        ctaLabel: "Open Manual",
        ctaHref: "/manual",
        tone: summary.manual.active_event_count > 0 ? "info" : "approved",
      },
    ],
  };
}
