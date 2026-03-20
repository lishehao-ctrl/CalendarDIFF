import type {
  ChangesWorkbenchSummary,
  OnboardingStatus,
  ChangeItem,
} from "@/lib/types";
import type { InitialReviewSummary } from "@/lib/import-review";
import { sourceDescriptor, summarizeChange } from "@/lib/presenters";

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

export function buildOverviewCards(params: {
  summary: ChangesWorkbenchSummary;
  topPendingChange: ChangeItem | null;
  onboarding: OnboardingStatus;
  initialReview: InitialReviewSummary;
}): OverviewCardVM[] {
  const { summary, topPendingChange, onboarding, initialReview } = params;
  const needsInitialReview = summary.baseline_review_pending > 0 || initialReview.readyCount > 0;

  const replayReviewSummary = topPendingChange
    ? `${summarizeChange(topPendingChange).title} is waiting from ${topPendingChange.primary_source ? sourceDescriptor(topPendingChange.primary_source) : "attached evidence"}.`
    : summary.changes_pending > 0
      ? `${summary.changes_pending} changes are waiting for review.`
      : "Nothing is waiting in Changes right now.";

  const sourceSummary = !onboarding.first_source_id
    ? onboarding.message || "Connect the required sources before trusting intake."
    : summary.sources.message;

  const namingSummary = summary.families.pending_raw_type_suggestions > 0
    ? `${summary.families.pending_raw_type_suggestions} suggestion${summary.families.pending_raw_type_suggestions === 1 ? "" : "s"} are waiting. ${summary.recommended_lane === "families" ? summary.recommended_action_reason : "Open Families to govern naming drift."}`
    : summary.families.last_error
      ? `Family governance needs attention. ${summary.families.last_error}`
      : "No naming drift is waiting right now.";

  const fallbackSummary = summary.manual.active_event_count > 0
    ? `${summary.manual.active_event_count} manual fallback${summary.manual.active_event_count === 1 ? "" : "s"} are active. Open Manual when the system cannot safely express canonical state.`
    : "No manual fallback work is open.";

  return [
    {
      key: "needs-review",
      eyebrow: initialReview.readyCount > 0 ? "Initial Review" : "Needs Review",
      title: initialReview.summaryTitle,
      metric: `${needsInitialReview ? summary.baseline_review_pending : summary.changes_pending}`,
      summary: initialReview.readyCount > 0 || initialReview.runningCount > 0 ? initialReview.summaryBody : replayReviewSummary,
      ctaLabel: initialReview.primaryCtaLabel,
      ctaHref: initialReview.primaryCtaHref,
      tone: needsInitialReview || initialReview.runningCount > 0 || summary.changes_pending > 0 ? "pending" : "approved",
    },
    {
      key: "source-posture",
      eyebrow: "Source Posture",
      title: "Check source posture",
      metric: `${summary.sources.active_count}`,
      summary: sourceSummary,
      ctaLabel: "Open Sources",
      ctaHref: "/sources",
      tone: summary.sources.attention_count > 0 || onboarding.stage !== "ready" ? "pending" : "approved",
    },
    {
      key: "naming-drift",
      eyebrow: "Naming Drift",
      title: "Review naming drift",
      metric: `${summary.families.pending_raw_type_suggestions}`,
      summary: namingSummary,
      ctaLabel: "Open Families",
      ctaHref: "/families",
      tone: summary.families.attention_count > 0 ? "pending" : "info",
    },
    {
      key: "fallbacks",
      eyebrow: "Fallbacks",
      title: "Handle fallback work",
      metric: `${summary.manual.active_event_count}`,
      summary: fallbackSummary,
      ctaLabel: "Open Manual",
      ctaHref: "/manual",
      tone: summary.manual.active_event_count > 0 ? "info" : "approved",
    },
  ];
}
