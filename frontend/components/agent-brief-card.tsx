"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/data-states";
import { agentWorkspaceContextCacheKey, getAgentWorkspaceContext } from "@/lib/api/agents";
import { withBasePath } from "@/lib/demo-mode";
import { translate } from "@/lib/i18n/runtime";
import { formatDateTime } from "@/lib/presenters";
import type { AgentBlockingCondition, AgentWorkspaceContext } from "@/lib/types";
import { useApiResource } from "@/lib/use-api-resource";

function riskTone(risk: string) {
  switch (risk) {
    case "low":
      return "approved";
    case "high":
      return "error";
    default:
      return "pending";
  }
}

function severityTone(severity: AgentBlockingCondition["severity"]) {
  switch (severity) {
    case "blocking":
      return "error";
    case "warning":
      return "pending";
    default:
      return "info";
  }
}

function laneHref(lane: AgentWorkspaceContext["recommended_next_action"]["lane"]) {
  return {
    sources: "/sources",
    initial_review: "/initial-review",
    changes: "/changes",
    families: "/families",
    manual: "/manual",
  }[lane];
}

export function AgentBriefCard({ basePath = "" }: { basePath?: string }) {
  const context = useApiResource<AgentWorkspaceContext>(() => getAgentWorkspaceContext(), [], null, {
    cacheKey: agentWorkspaceContextCacheKey(),
  });

  if (context.loading && !context.data) {
    return (
      <PanelLoadingPlaceholder
        eyebrow={translate("agent.brief.eyebrow")}
        title={translate("agent.brief.title")}
        rows={2}
      />
    );
  }

  if (context.error && !context.data) {
    return <ErrorState message={context.error} />;
  }

  if (!context.data) {
    return <EmptyState title={translate("agent.brief.eyebrow")} description={translate("agent.brief.unavailable")} />;
  }

  const recommendedLaneHref = withBasePath(basePath, laneHref(context.data.recommended_next_action.lane));
  const topChanges = context.data.top_pending_changes.slice(0, 3);
  const sourceBlocker = context.data.blocking_conditions.some((condition) => condition.code.includes("source"));

  return (
    <Card className="animate-surface-enter p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-3xl">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.brief.eyebrow")}</p>
          <h2 className="mt-2 text-xl font-semibold text-ink">{translate("agent.brief.title")}</h2>
          <p className="mt-3 text-sm leading-6 text-[#596270]">{context.data.recommended_next_action.reason}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge tone="info">{context.data.recommended_next_action.lane}</Badge>
          <Badge tone={riskTone(context.data.recommended_next_action.risk_level)}>{context.data.recommended_next_action.risk_level}</Badge>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-3">
        <Button asChild size="sm">
          <Link href={recommendedLaneHref}>
            {translate("agent.brief.openRecommendedLane")}
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </Button>
        {topChanges[0] ? (
          <Button asChild size="sm" variant="soft">
            <Link href={withBasePath(basePath, `/changes?focus=${topChanges[0].id}`)}>{translate("agent.brief.openTopChange")}</Link>
          </Button>
        ) : null}
        {sourceBlocker ? (
          <Button asChild size="sm" variant="ghost">
            <Link href={withBasePath(basePath, "/sources")}>{translate("agent.brief.openSources")}</Link>
          </Button>
        ) : null}
      </div>

      {context.data.blocking_conditions.length > 0 ? (
        <div className="mt-5">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.brief.blockers")}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {context.data.blocking_conditions.map((condition) => (
              <Badge key={`${condition.code}-${condition.message}`} tone={severityTone(condition.severity)}>
                {condition.message}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}

      {topChanges.length > 0 ? (
        <div className="mt-5">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.brief.topChanges")}</p>
          <div className="mt-3 space-y-2">
            {topChanges.map((change) => (
              <Link
                key={change.id}
                href={withBasePath(basePath, `/changes?focus=${change.id}`)}
                className="flex items-center justify-between rounded-[1rem] border border-line/80 bg-white/72 px-4 py-3 text-sm text-[#314051] transition hover:bg-white"
              >
                <span>{change.after_event?.event_display.display_label || change.after_display?.display_label || `Change #${change.id}`}</span>
                <span className="text-[#6d7885]">{formatDateTime(change.detected_at)}</span>
              </Link>
            ))}
          </div>
        </div>
      ) : null}
    </Card>
  );
}
