"use client";

import Link from "next/link";
import { ArrowRight, BellDot, GitCompareArrows, Link2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { getOnboardingStatus } from "@/lib/api/onboarding";
import { getReviewSummary } from "@/lib/api/review";
import { useApiResource } from "@/lib/use-api-resource";
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
import type { OnboardingStatus, ReviewSummary, SourceHealth } from "@/lib/types";

const actionCards = [
  {
    href: "/sources",
    label: "Sources",
    title: "Manage intake",
    description: "Connect or fix sources.",
    icon: BellDot
  },
  {
    href: "/review/changes",
    label: "Changes",
    title: "Review changes",
    description: "Approve or edit pending updates.",
    icon: GitCompareArrows
  },
  {
    href: "/review/links",
    label: "Family",
    title: "Manage families",
    description: "Labels and raw types.",
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
  const nextMoveTitle =
    summary.data.changes_pending > 0
      ? "Review pending changes"
      : sourceHealth.status === "attention"
        ? "Fix source health"
        : "Workspace looks stable";
  const nextMoveDetail =
    summary.data.changes_pending > 0
      ? `${summary.data.changes_pending} change${summary.data.changes_pending === 1 ? "" : "s"} are waiting for review.`
      : sourceHealth.message;

  return (
    <div className="space-y-4">
      <div className="px-1">
        <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">Overview</p>
        <h1 className="mt-1 text-2xl font-semibold text-ink">Workspace</h1>
      </div>

      <div className="flex flex-col gap-3 rounded-[1.2rem] border border-line/80 bg-white/72 px-4 py-3 shadow-[var(--shadow-panel)] md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap items-center gap-2 text-sm text-[#596270]">
          <span className="rounded-full bg-[rgba(20,32,44,0.06)] px-3 py-1.5 text-ink">{formatStatusLabel(stage)}</span>
          <span className="rounded-full bg-[rgba(20,32,44,0.06)] px-3 py-1.5 text-ink">{formatStatusLabel(sourceHealth.status)}</span>
          <span className="rounded-full bg-[rgba(20,32,44,0.06)] px-3 py-1.5 text-ink">{summary.data.changes_pending} changes</span>
          <span className="rounded-full bg-[rgba(20,32,44,0.06)] px-3 py-1.5 text-ink">{summary.data.link_candidates_pending} links</span>
        </div>
        <p className="text-sm text-[#596270]">Updated {formatDateTime(summary.data.generated_at, "recently")}</p>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.08fr)_minmax(320px,0.92fr)]">
        <Card className="p-4">
          <div className="flex items-start justify-between gap-4">
            <div className="max-w-2xl">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Next move</p>
              <h2 className="mt-2 text-lg font-semibold text-ink">{nextMoveTitle}</h2>
              <p className="mt-1 text-sm text-[#596270]">{nextMoveDetail}</p>
            </div>
            <Badge tone={sourceHealthTone(sourceHealth.status)}>{formatStatusLabel(sourceHealth.status)}</Badge>
          </div>
          <div className="mt-4 rounded-[1.1rem] border border-line/80 bg-white/60 p-4 text-sm text-[#314051]">
            <p>{onboarding.data.message || "Workspace summary available."}</p>
            {sourceHealth.affected_provider ? <p className="mt-2 text-[#596270]">Provider: {formatStatusLabel(sourceHealth.affected_provider)}</p> : null}
            {sourceHealth.affected_source_id ? <p className="mt-1 text-[#596270]">Source #{sourceHealth.affected_source_id}</p> : null}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link href={nextActionHref}>
              <Button size="sm">
                {nextActionLabel}
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </Link>
            <Link href="/review/links">
              <Button size="sm" variant="ghost">Open family</Button>
            </Link>
          </div>
        </Card>

        <Card className="p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Shortcuts</p>
              <h2 className="mt-2 text-lg font-semibold text-ink">Jump to a lane</h2>
            </div>
            <Badge tone={readinessTone(stage)}>{formatStatusLabel(stage)}</Badge>
          </div>
          <div className="mt-4 grid gap-3">
            {actionCards.map(({ href, label, title, description, icon: Icon }) => (
              <Link key={href} href={href} className="rounded-[1.1rem] border border-line/80 bg-white/60 p-4 transition hover:bg-white">
                <div className="flex items-start gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[rgba(20,32,44,0.06)] text-ink">
                    <Icon className="h-4 w-4" />
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{label}</p>
                    <p className="mt-1 font-medium text-ink">{title}</p>
                    <p className="mt-1 text-sm text-[#596270]">{description}</p>
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
