"use client";

import Link from "next/link";
import { ArrowRight, BellDot, GitCompareArrows, Link2, Pencil, ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/data-states";
import { getOnboardingStatus } from "@/lib/api/onboarding";
import { getReviewSummary, listReviewChanges } from "@/lib/api/review";
import { listSources } from "@/lib/api/sources";
import { listCourseWorkItemFamilies } from "@/lib/api/users";
import { withBasePath } from "@/lib/demo-mode";
import { formatDateTime, sourceDescriptor } from "@/lib/presenters";
import { buildIntakePosture, buildSourceObservabilityViews } from "@/lib/source-observability";
import type { CourseWorkItemFamily, OnboardingStatus, ReviewChange, ReviewSummary, SourceRow } from "@/lib/types";
import { useApiResource } from "@/lib/use-api-resource";

type CourseHotspot = {
  courseDisplay: string;
  pendingChanges: number;
  familyCount: number;
  rawTypeCount: number;
  leadLabel: string;
};

type AttentionState = {
  title: string;
  detail: string;
  href: string;
  action: string;
  secondaryHref: string;
  secondaryAction: string;
};

const laneCards = [
  {
    href: "/sources",
    label: "Sources",
    title: "Inspect intake",
    description: "Reconnect or sync sources.",
    icon: BellDot,
  },
  {
    href: "/review/changes",
    label: "Changes",
    title: "Review changes",
    description: "Approve or reject updates.",
    icon: GitCompareArrows,
  },
  {
    href: "/families",
    label: "Families",
    title: "Clean up families",
    description: "Merge drift and relabel.",
    icon: Link2,
  },
  {
    href: "/manual",
    label: "Manual",
    title: "Repair exceptions",
    description: "Use as fallback.",
    icon: Pencil,
  },
] as const;

function buildHotspots(changes: ReviewChange[], families: CourseWorkItemFamily[]) {
  const byCourse = new Map<string, CourseHotspot>();

  for (const change of changes) {
    const courseDisplay = change.after_event?.event_display.course_display || change.before_event?.event_display.course_display || "Unknown course";
    const existing = byCourse.get(courseDisplay) || {
      courseDisplay,
      pendingChanges: 0,
      familyCount: 0,
      rawTypeCount: 0,
      leadLabel: change.after_event?.event_display.display_label || change.before_event?.event_display.display_label || "Timeline item",
    };
    existing.pendingChanges += 1;
    byCourse.set(courseDisplay, existing);
  }

  for (const family of families) {
    const existing = byCourse.get(family.course_display) || {
      courseDisplay: family.course_display,
      pendingChanges: 0,
      familyCount: 0,
      rawTypeCount: 0,
      leadLabel: family.canonical_label,
    };
    existing.familyCount += 1;
    existing.rawTypeCount += family.raw_types.length;
    if (!existing.leadLabel) {
      existing.leadLabel = family.canonical_label;
    }
    byCourse.set(family.course_display, existing);
  }

  return Array.from(byCourse.values())
    .sort((left, right) => {
      if (right.pendingChanges !== left.pendingChanges) return right.pendingChanges - left.pendingChanges;
      if (right.rawTypeCount !== left.rawTypeCount) return right.rawTypeCount - left.rawTypeCount;
      if (right.familyCount !== left.familyCount) return right.familyCount - left.familyCount;
      return left.courseDisplay.localeCompare(right.courseDisplay);
    })
    .slice(0, 6);
}

function buildSourceIssueRows(sources: SourceRow[], onboarding: OnboardingStatus) {
  const rows = sources
    .filter((source) => source.last_error_message || source.config_state === "rebind_pending" || source.oauth_connection_status === "not_connected")
    .map((source) => ({
      key: `source-${source.source_id}`,
      label: source.display_name || source.provider || `Source ${source.source_id}`,
      message:
        source.last_error_message ||
        (source.config_state === "rebind_pending" ? "This source needs rebind before intake is trustworthy." : "This source needs reconnect."),
    }));

  if (rows.length === 0 && onboarding.source_health && onboarding.source_health.status !== "healthy") {
    rows.push({
      key: "onboarding-source-health",
      label: onboarding.source_health.affected_provider || "Source posture",
      message: onboarding.source_health.message,
    });
  }

  if (rows.length === 0 && onboarding.stage !== "ready") {
    rows.push({
      key: "onboarding-stage",
      label: "Setup posture",
      message: onboarding.message || "Workspace setup is still incomplete.",
    });
  }

  return rows;
}

function buildAttentionState(params: {
  pendingChanges: ReviewChange[];
  sourceIssueCount: number;
  driftingFamilyCount: number;
}): AttentionState {
  const { pendingChanges, sourceIssueCount, driftingFamilyCount } = params;
  const mainChange = pendingChanges[0] || null;

  if (pendingChanges.length > 0) {
    const label = mainChange?.after_event?.event_display.display_label || mainChange?.before_event?.event_display.display_label || "timeline item";
    const source = mainChange?.primary_source ? sourceDescriptor(mainChange.primary_source) : "attached evidence";
    return {
      title: `${pendingChanges.length} pending change${pendingChanges.length === 1 ? "" : "s"} need timeline decisions.`,
      detail: `${label} is waiting in Changes through ${source}.`,
      href: "/review/changes",
      action: "Open changes",
      secondaryHref: "/sources",
      secondaryAction: "Inspect sources",
    };
  }

  if (sourceIssueCount > 0) {
    return {
      title: sourceIssueCount === 1 ? "Source posture needs attention before you trust new signals." : `${sourceIssueCount} source issues need repair before intake is trustworthy.`,
      detail: "Fix Sources before trusting the next review cycle.",
      href: "/sources",
      action: "Inspect source health",
      secondaryHref: "/review/changes",
      secondaryAction: "Open changes",
    };
  }

  if (driftingFamilyCount > 0) {
    return {
      title: `${driftingFamilyCount} family${driftingFamilyCount === 1 ? "" : "ies"} show naming drift.`,
      detail: "Naming drift is rising even though the change queue is calm.",
      href: "/families",
      action: "Review families",
      secondaryHref: "/review/changes",
      secondaryAction: "Open changes",
    };
  }

  return {
    title: "No urgent review work is waiting right now.",
    detail: "Changes are calm and intake looks usable.",
    href: "/review/changes",
    action: "Open changes",
    secondaryHref: "/sources",
    secondaryAction: "Inspect sources",
  };
}

function getOverviewError(params: {
  changesError: string | null;
  sourcesError: string | null;
  familiesError: string | null;
  onboardingError: string | null;
  summaryError: string | null;
  basePath: string;
}) {
  const { changesError, sourcesError, familiesError, onboardingError, summaryError, basePath } = params;

  if (changesError) {
    return {
      message: `Changes could not be loaded for Overview. ${changesError}`,
      actionLabel: "Open Changes",
      actionHref: withBasePath(basePath, "/review/changes"),
    };
  }
  if (sourcesError || onboardingError) {
    return {
      message: `Source posture could not be loaded for Overview. ${sourcesError || onboardingError}`,
      actionLabel: "Open Sources",
      actionHref: withBasePath(basePath, "/sources"),
    };
  }
  if (familiesError) {
    return {
      message: `Families could not be loaded for Overview. ${familiesError}`,
      actionLabel: "Open Families",
      actionHref: withBasePath(basePath, "/families"),
    };
  }
  if (summaryError) {
    return {
      message: `Workspace summary could not be loaded. ${summaryError}`,
      actionLabel: "Open Changes",
      actionHref: withBasePath(basePath, "/review/changes"),
    };
  }
  return null;
}

export default function OverviewPage({ basePath = "" }: { basePath?: string }) {
  const onboarding = useApiResource<OnboardingStatus>(() => getOnboardingStatus(), []);
  const summary = useApiResource<ReviewSummary>(() => getReviewSummary(), []);
  const pendingChanges = useApiResource<ReviewChange[]>(() => listReviewChanges({ review_status: "pending", limit: 50 }), []);
  const sources = useApiResource<SourceRow[]>(() => listSources({ status: "active" }), []);
  const families = useApiResource<CourseWorkItemFamily[]>(() => listCourseWorkItemFamilies(), []);

  if (onboarding.loading || summary.loading || pendingChanges.loading || sources.loading || families.loading) {
    return <LoadingState label="overview" />;
  }

  const errorState = getOverviewError({
    changesError: pendingChanges.error,
    sourcesError: sources.error,
    familiesError: families.error,
    onboardingError: onboarding.error,
    summaryError: summary.error,
    basePath,
  });
  if (errorState) {
    return <ErrorState message={errorState.message} actionLabel={errorState.actionLabel} actionHref={errorState.actionHref} />;
  }

  if (!onboarding.data || !summary.data || !pendingChanges.data || !sources.data || !families.data) {
    return <ErrorState message="Overview could not assemble the current workspace state." />;
  }

  const sourceIssueRows = buildSourceIssueRows(sources.data, onboarding.data);
  const driftingFamilies = families.data.filter((family) => family.raw_types.length >= 3);
  const hotspots = buildHotspots(pendingChanges.data, families.data);
  const showBlockersCard = sourceIssueRows.length > 0 || onboarding.data.stage !== "ready";
  const observabilityViews = buildSourceObservabilityViews(sources.data, { previewMode: basePath === "/preview" });
  const intakePosture = buildIntakePosture(observabilityViews);
  const attention = buildAttentionState({
    pendingChanges: pendingChanges.data,
    sourceIssueCount: sourceIssueRows.length,
    driftingFamilyCount: driftingFamilies.length,
  });

  return (
    <div className="space-y-5">
      <div className="px-1">
        <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">Overview</p>
        <h1 className="mt-1 text-2xl font-semibold text-ink">Attention router</h1>
      </div>

      <div className={`grid gap-4 ${showBlockersCard ? "xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]" : ""}`}>
        <Card className="animate-surface-enter relative overflow-hidden p-6 md:p-7">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.14),transparent_36%),radial-gradient(circle_at_82%_18%,rgba(215,90,45,0.12),transparent_26%)]" />
          <div className="relative space-y-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="max-w-3xl">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Primary attention</p>
                <h2 className="mt-3 text-3xl font-semibold text-ink">{attention.title}</h2>
                <p className="mt-3 text-sm leading-7 text-[#596270]">{attention.detail}</p>
              </div>
              <div className="hidden flex-wrap gap-2 md:flex">
                <Badge tone={pendingChanges.data.length > 0 ? "pending" : "approved"}>{pendingChanges.data.length} pending changes</Badge>
                <Badge tone={sourceIssueRows.length > 0 ? "error" : "approved"}>{sourceIssueRows.length} source issues</Badge>
                <Badge tone={driftingFamilies.length > 0 ? "pending" : "info"}>{driftingFamilies.length} drifting families</Badge>
              </div>
            </div>

            <div className="hidden gap-3 md:grid-cols-3 md:grid">
              <div className="rounded-[1.15rem] border border-line/80 bg-white/75 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Changes</p>
                <p className="mt-2 text-2xl font-semibold text-ink">{pendingChanges.data.length}</p>
                <p className="mt-1 text-sm text-[#596270]">Waiting review.</p>
              </div>
              <div className="rounded-[1.15rem] border border-line/80 bg-white/75 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Source health</p>
                <p className="mt-2 text-2xl font-semibold text-ink">{sourceIssueRows.length}</p>
                <p className="mt-1 text-sm text-[#596270]">Need repair.</p>
              </div>
              <div className="rounded-[1.15rem] border border-line/80 bg-white/75 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Family drift</p>
                <p className="mt-2 text-2xl font-semibold text-ink">{driftingFamilies.length}</p>
                <p className="mt-1 text-sm text-[#596270]">Need cleanup.</p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Link href={withBasePath(basePath, attention.href)}>
                <Button>
                  {attention.action}
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </Link>
              <Link href={withBasePath(basePath, attention.secondaryHref)}>
                <Button variant="ghost">{attention.secondaryAction}</Button>
              </Link>
              <Link href={withBasePath(basePath, "/families")}>
                <Button variant="ghost">Open families</Button>
              </Link>
            </div>
          </div>
        </Card>

        {showBlockersCard ? (
        <Card className="animate-surface-enter animate-surface-delay-1 hidden p-5 xl:block">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Intake posture</p>
              <h2 className="mt-2 text-lg font-semibold text-ink">Bootstrap vs replay</h2>
            </div>
            <Badge tone={onboarding.data.source_health?.status === "healthy" ? "approved" : "pending"}>
              {onboarding.data.source_health?.status || onboarding.data.stage}
            </Badge>
          </div>

          <div className="mt-4 grid gap-3">
            <div className="rounded-[1rem] border border-line/80 bg-white/75 p-4">
              <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">Bootstrap</p>
              <p className="mt-2 text-sm font-medium text-ink">{intakePosture.warming_label}</p>
            </div>
            <div className="rounded-[1rem] border border-line/80 bg-white/75 p-4">
              <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">Replay</p>
              <p className="mt-2 text-sm font-medium text-ink">{intakePosture.replay_label}</p>
            </div>
            <div className="rounded-[1rem] border border-line/80 bg-white/75 p-4">
              <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">LLM cost</p>
              <p className="mt-2 text-sm font-medium text-ink">{intakePosture.cost_label}</p>
            </div>
            {sourceIssueRows.length > 0 ? (
              <div className="rounded-[1rem] border border-[rgba(215,90,45,0.22)] bg-[#fff6f2] p-4 text-sm text-[#7f3d2a]">
                <div className="flex items-center gap-2 font-medium text-ink">
                  <ShieldAlert className="h-4 w-4 text-ember" />
                  {sourceIssueRows[0].label}
                </div>
                <p className="mt-2 leading-6">{sourceIssueRows[0].message}</p>
              </div>
            ) : null}
          </div>
        </Card>
        ) : null}
      </div>

      <Card className="animate-surface-enter animate-surface-delay-1 p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Course hotspots</p>
            <h2 className="mt-2 text-lg font-semibold text-ink">Where the mess is building</h2>
          </div>
          <Badge tone="info">{hotspots.length} hotspot{hotspots.length === 1 ? "" : "s"}</Badge>
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {hotspots.length > 0 ? (
            hotspots.map((hotspot, index) => (
              <div
                key={hotspot.courseDisplay}
                className={`${index > 1 ? "hidden md:block " : ""}animate-surface-enter interactive-lift rounded-[1.15rem] border border-line/80 bg-white/72 p-4 transition-all duration-300 hover:-translate-y-0.5 hover:bg-white`}
                style={{ transitionDelay: `${index * 30}ms` }}
              >
                <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Course</p>
                  <h3 className="mt-1 text-base font-semibold text-ink">{hotspot.courseDisplay}</h3>
                  <p className="mt-2 text-sm text-[#596270]">{hotspot.leadLabel}</p>
                </div>
                <Badge tone={hotspot.pendingChanges > 0 ? "pending" : "info"}>{hotspot.pendingChanges} pending</Badge>
              </div>
                <div className="mt-4 hidden flex-wrap gap-2 text-sm text-[#314051] md:flex">
                  <span className="rounded-full border border-line/80 bg-white/80 px-3 py-1.5">{hotspot.familyCount} families</span>
                  <span className="rounded-full border border-line/80 bg-white/80 px-3 py-1.5">{hotspot.rawTypeCount} raw labels</span>
                </div>
              </div>
            ))
          ) : (
            <div className="rounded-[1.15rem] border border-dashed border-line/80 bg-white/40 p-6 text-sm text-[#596270]">
              No course is spiking right now. When pending changes or family drift return, this section will surface the first course to inspect.
            </div>
          )}
        </div>
      </Card>

      <Card className="animate-surface-enter animate-surface-delay-2 hidden p-5 md:block">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Secondary lanes</p>
            <h2 className="mt-2 text-lg font-semibold text-ink">Other lanes</h2>
          </div>
        </div>

        <div className="mt-4 grid gap-3 xl:grid-cols-4">
          {laneCards.map(({ href, label, title, description, icon: Icon }) => (
            <Link
              key={href}
              href={withBasePath(basePath, href)}
              className="rounded-[1.1rem] border border-line/80 bg-white/72 p-4 transition-all duration-300 hover:-translate-y-0.5 hover:bg-white"
            >
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[rgba(20,32,44,0.06)] text-ink">
                  <Icon className="h-4 w-4" />
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{label}</p>
                  <p className="mt-1 font-medium text-ink">{title}</p>
                  <p className="mt-2 text-sm leading-6 text-[#596270]">{description}</p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </Card>
    </div>
  );
}
