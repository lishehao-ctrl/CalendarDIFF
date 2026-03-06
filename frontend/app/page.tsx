"use client";

import Link from "next/link";
import { ArrowRight, CalendarClock, Link2, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { SummaryGrid } from "@/components/summary-grid";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { backendFetch } from "@/lib/backend";
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
import type { OnboardingStatus, ReviewSummary } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

const quickRoutes = [
  {
    href: "/sources",
    title: "Bring in an ICS feed",
    description: "Attach a calendar source, trigger a manual sync, and watch the pipeline wake up.",
    icon: CalendarClock
  },
  {
    href: "/review/changes",
    title: "Triage the review queue",
    description: "Approve canonical changes, reject noise, and inspect evidence before it lands.",
    icon: Sparkles
  },
  {
    href: "/review/links",
    title: "Resolve ambiguous links",
    description: "Clear candidates and alerts before they calcify into bad entity bindings.",
    icon: Link2
  }
] as const;

const stageCopy: Record<string, { label: string; note: string }> = {
  needs_user: {
    label: "Operator profile missing",
    note: "Create the first workspace identity so source ownership, reviews, and digests have a stable operator context."
  },
  needs_source_connection: {
    label: "Profile ready, feed missing",
    note: "The system is waiting for at least one active source before it can emit sync or review work."
  },
  ready: {
    label: "Workspace active",
    note: "The intake loop is live. Use this console to drive syncs, moderate changes, and keep link drift contained."
  }
};

export default function OverviewPage() {
  const onboarding = useResource<OnboardingStatus>("/onboarding/status");
  const summary = useResource<ReviewSummary>("/review/summary");
  const [notifyEmail, setNotifyEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const stage = onboarding.data?.stage || "unknown";
  const stageMeta = stageCopy[stage] || {
    label: formatStatusLabel(stage, "Unknown stage"),
    note: onboarding.data?.message || "The backend returned a stage we do not explicitly map yet."
  };
  const summaryBlocked = Boolean(summary.error && stage !== "ready");
  const error = onboarding.error || (stage === "ready" ? summary.error : null);

  const stats = useMemo(
    () => [
      {
        label: "Onboarding stage",
        value: stageMeta.label,
        detail: onboarding.data?.message || stageMeta.note
      },
      {
        label: "Pending changes",
        value: String(summaryBlocked ? 0 : summary.data?.changes_pending ?? 0),
        detail: summaryBlocked ? "Blocked until an active source is connected." : "Canonical review items waiting for operator approval."
      },
      {
        label: "Pending candidates",
        value: String(summaryBlocked ? 0 : summary.data?.link_candidates_pending ?? 0),
        detail: summaryBlocked ? "Link review stays dormant before the first active source." : "Potential cross-source joins that still need a decision."
      },
      {
        label: "Pending alerts",
        value: String(summaryBlocked ? 0 : summary.data?.link_alerts_pending ?? 0),
        detail: summaryBlocked ? "Alerts begin only after source intake is live." : `Snapshot generated ${formatDateTime(summary.data?.generated_at, "just now")}.`
      }
    ],
    [onboarding.data?.message, stageMeta.label, stageMeta.note, summaryBlocked, summary.data?.changes_pending, summary.data?.generated_at, summary.data?.link_alerts_pending, summary.data?.link_candidates_pending]
  );

  async function register() {
    setSubmitting(true);
    try {
      await backendFetch("/onboarding/registrations", {
        method: "POST",
        body: JSON.stringify({ notify_email: notifyEmail })
      });
      await onboarding.refresh();
      await summary.refresh();
      setNotifyEmail("");
    } finally {
      setSubmitting(false);
    }
  }

  if (onboarding.loading || summary.loading) return <LoadingState label="overview" />;
  if (error) return <ErrorState message={error} />;
  if (!onboarding.data) {
    return <EmptyState title="No onboarding payload returned" description="The backend did not return workspace status, so the console cannot infer the next step." />;
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Workspace"
        title="Overview"
        description="A single editorial control room for onboarding, intake pressure, review readiness, and link governance."
        badge={stageMeta.label}
      />

      <div className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
        <Card className="relative overflow-hidden p-6 md:p-7">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.16),transparent_42%),radial-gradient(circle_at_80%_20%,rgba(215,90,45,0.12),transparent_30%)]" />
          <div className="relative flex h-full flex-col justify-between gap-6">
            <div>
              <p className="text-xs uppercase tracking-[0.24em] text-[#596270]">Current posture</p>
              <h3 className="mt-3 max-w-2xl text-3xl font-semibold text-ink md:text-4xl">{stageMeta.label}</h3>
              <p className="mt-4 max-w-2xl text-sm leading-7 text-[#314051]">{stageMeta.note}</p>
              {onboarding.data.last_error ? (
                <div className="mt-4 rounded-[1.15rem] border border-[#efc4b5] bg-[#fff3ef] px-4 py-3 text-sm text-[#7f3d2a]">
                  Last onboarding error: {onboarding.data.last_error}
                </div>
              ) : null}
              {summaryBlocked ? (
                <div className="mt-4 rounded-[1.15rem] border border-line/80 bg-white/65 px-4 py-3 text-sm text-[#314051]">
                  Review metrics stay dormant until at least one source is active. The workspace itself is still healthy enough to continue onboarding.
                </div>
              ) : null}
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-[1.25rem] border border-line/80 bg-white/65 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Registered user</p>
                <p className="mt-2 text-lg font-semibold">{onboarding.data.registered_user_id ? `User #${onboarding.data.registered_user_id}` : "Not created yet"}</p>
              </div>
              <div className="rounded-[1.25rem] border border-line/80 bg-white/65 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">First active source</p>
                <p className="mt-2 text-lg font-semibold">{onboarding.data.first_source_id ? `Source #${onboarding.data.first_source_id}` : "No source connected"}</p>
              </div>
            </div>
          </div>
        </Card>

        <Card className="p-6 md:p-7">
          <p className="text-xs uppercase tracking-[0.24em] text-[#596270]">Next action</p>
          <h3 className="mt-3 text-2xl font-semibold">Drive the next stable state</h3>
          <p className="mt-3 text-sm leading-7 text-[#596270]">
            The console stays intentionally biased toward decisive next steps: create the operator, connect a feed, or clear the review queue.
          </p>

          {stage === "needs_user" ? (
            <div className="mt-6 space-y-4">
              <div>
                <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="notify-email">
                  Notify email
                </label>
                <Input
                  id="notify-email"
                  value={notifyEmail}
                  onChange={(event) => setNotifyEmail(event.target.value)}
                  placeholder="notify@example.com"
                />
              </div>
              <Button disabled={submitting || !notifyEmail} onClick={() => void register()}>
                {submitting ? "Creating profile..." : "Create workspace owner"}
              </Button>
            </div>
          ) : stage === "needs_source_connection" ? (
            <div className="mt-6 rounded-[1.25rem] border border-line/80 bg-white/55 p-4">
              <p className="text-sm text-[#314051]">A user exists. The next stable step is adding an ICS source so sync and review requests can start flowing.</p>
              <Link className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-cobalt" href="/sources">
                Open source control <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          ) : (
            <div className="mt-6 rounded-[1.25rem] border border-line/80 bg-white/55 p-4">
              <p className="text-sm text-[#314051]">The workspace is operational. Focus on queue throughput, ambiguous links, and evidence-backed review velocity.</p>
              <div className="mt-4 flex flex-wrap gap-3">
                <Link className="inline-flex items-center gap-2 text-sm font-medium text-cobalt" href="/review/changes">
                  Open review inbox <ArrowRight className="h-4 w-4" />
                </Link>
                <Link className="inline-flex items-center gap-2 text-sm font-medium text-cobalt" href="/review/links">
                  Open link workspace <ArrowRight className="h-4 w-4" />
                </Link>
              </div>
            </div>
          )}
        </Card>
      </div>

      <SummaryGrid items={stats} />

      <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
        <Card className="p-6">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Launch paths</p>
          <div className="mt-5 space-y-3">
            {quickRoutes.map(({ href, title, description, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className="flex items-start justify-between gap-4 rounded-[1.25rem] border border-line/80 bg-white/60 px-4 py-4 transition hover:-translate-y-0.5 hover:bg-white"
              >
                <div className="flex gap-4">
                  <div className="mt-0.5 flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(20,32,44,0.06)] text-ink">
                    <Icon className="h-4 w-4" />
                  </div>
                  <div>
                    <p className="text-base font-semibold text-ink">{title}</p>
                    <p className="mt-1 text-sm leading-6 text-[#596270]">{description}</p>
                  </div>
                </div>
                <ArrowRight className="mt-1 h-4 w-4 text-[#718090]" />
              </Link>
            ))}
          </div>
        </Card>

        <Card className="p-6">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Operating notes</p>
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <div className="rounded-[1.25rem] border border-line/80 bg-white/60 p-4">
              <p className="text-sm font-semibold">Real API through a Next proxy</p>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                The browser never sees `APP_API_KEY`. Every request flows through the frontend route handler and inherits server-side backend credentials.
              </p>
            </div>
            <div className="rounded-[1.25rem] border border-line/80 bg-white/60 p-4">
              <p className="text-sm font-semibold">Gmail auth stays intentionally blocked</p>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                The MVP UI keeps Gmail visible as a source family, but it does not ship real OAuth until the backend auth path is finalized.
              </p>
            </div>
            <div className="rounded-[1.25rem] border border-line/80 bg-white/60 p-4 md:col-span-2">
              <p className="text-sm font-semibold">Current queue interpretation</p>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                Pending changes indicate moderation workload. Pending candidates indicate uncertain entity joins. Pending alerts indicate automatic links that still need human confirmation.
              </p>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
