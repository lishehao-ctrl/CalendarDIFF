"use client";

import Link from "next/link";
import { ArrowRight, BellDot, CheckCircle2, GitCompareArrows, Link2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { SummaryGrid } from "@/components/summary-grid";
import { getOnboardingStatus } from "@/lib/api/onboarding";
import { getReviewSummary } from "@/lib/api/review";
import { useApiResource } from "@/lib/use-api-resource";
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
import type { OnboardingStatus, ReviewSummary, SourceHealth } from "@/lib/types";

const actionCards = [
  {
    href: "/sources",
    eyebrow: "Sources",
    title: "Connect intake",
    description: "Add or maintain Canvas and Gmail sources, then trigger a sync when you need fresh signals.",
    icon: BellDot
  },
  {
    href: "/review/changes",
    eyebrow: "Changes",
    title: "Review detected updates",
    description: "Approve, reject, or edit incoming deadline changes with evidence beside each decision.",
    icon: GitCompareArrows
  },
  {
    href: "/review/links",
    eyebrow: "Links",
    title: "Repair matching issues",
    description: "Approve candidates, relink mismatches, and keep do-not-link safeguards tidy.",
    icon: Link2
  }
] as const;

function readinessTone(stage: string | null | undefined): "approved" | "pending" | "default" {
  if (stage === "ready") {
    return "approved";
  }
  if (stage) {
    return "pending";
  }
  return "default";
}

function sourceHealthTone(status: SourceHealth["status"] | undefined): "approved" | "pending" | "default" {
  if (status === "healthy") {
    return "approved";
  }
  if (status === "attention") {
    return "pending";
  }
  return "default";
}

function fallbackSourceHealth(stage: string): SourceHealth {
  if (stage === "needs_source_connection") {
    return {
      status: "disconnected",
      message: "No active sources connected yet.",
      affected_source_id: null,
      affected_provider: null,
    };
  }
  return {
    status: "healthy",
    message: "Connected sources are ready for intake.",
    affected_source_id: null,
    affected_provider: null,
  };
}

export default function OverviewPage() {
  const onboarding = useApiResource<OnboardingStatus>(() => getOnboardingStatus(), []);
  const summary = useApiResource<ReviewSummary>(() => getReviewSummary(), []);

  if (onboarding.loading || summary.loading) {
    return <LoadingState label="overview" />;
  }

  if (onboarding.error) {
    return <ErrorState message={onboarding.error} />;
  }

  if (summary.error) {
    return <ErrorState message={summary.error} />;
  }

  if (!onboarding.data || !summary.data) {
    return <EmptyState title="Overview unavailable" description="The workspace summary could not be loaded." />;
  }

  const stage = onboarding.data.stage || "unknown";
  const sourceHealth = onboarding.data.source_health || fallbackSourceHealth(stage);
  const nextActionHref = stage === "ready" ? "/review/changes" : "/sources";
  const nextActionLabel = stage === "ready" ? "Open changes queue" : "Connect a source";
  const summaryItems = [
    {
      label: "Workspace",
      value: formatStatusLabel(stage),
      detail: onboarding.data.message || "Current readiness state"
    },
    {
      label: "Source health",
      value: formatStatusLabel(sourceHealth.status),
      detail: sourceHealth.message
    },
    {
      label: "Changes",
      value: String(summary.data.changes_pending),
      detail: "Items waiting for review"
    },
    {
      label: "Link candidates",
      value: String(summary.data.link_candidates_pending),
      detail: `Snapshot from ${formatDateTime(summary.data.generated_at, "recently")}`
    }
  ];

  return (
    <div className="space-y-5">
      <Card className="relative overflow-hidden px-6 py-7 md:px-8 md:py-8">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.16),transparent_34%),radial-gradient(circle_at_82%_18%,rgba(215,90,45,0.14),transparent_28%)]" />
        <div className="relative grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="max-w-3xl">
            <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">Overview</p>
            <h1 className="mt-3 text-3xl font-semibold text-ink md:text-4xl">See what needs attention, then move straight into the right lane.</h1>
            <p className="mt-4 text-sm leading-7 text-[#596270]">
              CalendarDIFF works best when the home page answers three questions quickly: are sources healthy, how much review is waiting, and what should you do next.
            </p>
            <div className="relative mt-6 flex flex-wrap gap-3">
              <Link href={nextActionHref}>
                <Button>
                  {nextActionLabel}
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </Link>
              <Link href="/review/links">
                <Button variant="ghost">Open link review</Button>
              </Link>
            </div>
          </div>
          <Card className="relative border-white/40 bg-white/55 p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Today</p>
                <h2 className="mt-3 text-xl font-semibold text-ink">Next best move</h2>
              </div>
              <Badge tone={readinessTone(stage)}>{formatStatusLabel(stage)}</Badge>
            </div>
            <div className="mt-4 space-y-3 text-sm text-[#314051]">
              <p>{sourceHealth.message}</p>
              <div className="rounded-[1.1rem] border border-line/80 bg-white/70 p-4">
                <div className="flex items-center gap-2 text-ink">
                  <CheckCircle2 className="h-4 w-4 text-moss" />
                  <span className="font-medium">{summary.data.changes_pending > 0 ? "Start with the review inbox." : "No change backlog right now."}</span>
                </div>
                <p className="mt-2 text-[#596270]">
                  {summary.data.changes_pending > 0
                    ? `${summary.data.changes_pending} change${summary.data.changes_pending === 1 ? "" : "s"} are waiting for a decision.`
                    : `${summary.data.link_candidates_pending} link candidate${summary.data.link_candidates_pending === 1 ? "" : "s"} still need attention.`}
                </p>
              </div>
            </div>
          </Card>
        </div>
      </Card>
      <SummaryGrid items={summaryItems} />
      <div className="grid gap-5 xl:grid-cols-[1fr_0.92fr]">
        <Card className="p-6 md:p-7">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Source health</p>
              <h2 className="mt-3 text-2xl font-semibold">Keep intake healthy</h2>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                Healthy intake keeps everything else quiet. When a source needs attention, fix it here before the review queue gets noisy.
              </p>
            </div>
            <Badge tone={sourceHealthTone(sourceHealth.status)}>{formatStatusLabel(sourceHealth.status)}</Badge>
          </div>
          <div className="mt-5 rounded-[1.2rem] border border-line/80 bg-white/60 p-5 text-sm text-[#314051]">
            <p>{sourceHealth.message}</p>
            {sourceHealth.affected_provider ? <p className="mt-3 text-[#596270]">Affected provider: {formatStatusLabel(sourceHealth.affected_provider)}</p> : null}
            {sourceHealth.affected_source_id ? <p className="mt-1 text-[#596270]">Source #{sourceHealth.affected_source_id}</p> : null}
          </div>
        </Card>
        <Card className="p-6 md:p-7">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Workflows</p>
          <div className="mt-4 grid gap-3">
            {actionCards.map(({ href, eyebrow, title, description, icon: Icon }) => (
              <Link key={href} href={href} className="rounded-[1.25rem] border border-line/80 bg-white/60 p-4 transition hover:-translate-y-0.5 hover:bg-white">
                <div className="flex items-start gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[rgba(31,94,255,0.1)] text-cobalt">
                    <Icon className="h-4 w-4" />
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{eyebrow}</p>
                    <p className="mt-2 font-medium text-ink">{title}</p>
                    <p className="mt-2 text-sm leading-6 text-[#596270]">{description}</p>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
