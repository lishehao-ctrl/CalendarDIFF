"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { AgentDisclosure } from "@/components/agent-step-flow";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/data-states";
import { agentWorkspaceContextCacheKey, getAgentWorkspaceContext } from "@/lib/api/agents";
import { withBasePath } from "@/lib/demo-mode";
import { translate } from "@/lib/i18n/runtime";
import { formatStatusLabel } from "@/lib/presenters";
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
    initial_review: "/changes?bucket=initial_review",
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
    return <PanelLoadingPlaceholder eyebrow={translate("agent.brief.eyebrow")} title={translate("agent.brief.title")} rows={2} />;
  }

  if (context.error && !context.data) {
    return <ErrorState message={context.error} />;
  }

  if (!context.data) {
    return <EmptyState title={translate("agent.brief.eyebrow")} description={translate("agent.brief.unavailable")} />;
  }

  const recommendedLaneHref = withBasePath(basePath, laneHref(context.data.recommended_next_action.lane));
  const sourceBlocker = context.data.blocking_conditions.some((condition) => condition.code.includes("source"));
  const recommendedLane = context.data.recommended_next_action.lane;

  return (
    <Card className="animate-surface-enter p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.brief.eyebrow")}</p>
          <h2 className="mt-2 text-lg font-semibold text-ink">{translate("agent.brief.title")}</h2>
          <p className="mt-2 text-sm leading-6 text-[#596270]">{context.data.recommended_next_action.reason}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge tone="info">{formatStatusLabel(context.data.recommended_next_action.lane)}</Badge>
          <Badge tone={riskTone(context.data.recommended_next_action.risk_level)}>{formatStatusLabel(context.data.recommended_next_action.risk_level)}</Badge>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <Button asChild size="sm">
          <Link href={recommendedLaneHref}>
            {translate("agent.brief.openRecommendedLane")}
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </Button>
        {sourceBlocker && recommendedLane !== "sources" ? (
          <Button asChild size="sm" variant="ghost">
            <Link href={withBasePath(basePath, "/sources")}>{translate("agent.brief.openSources")}</Link>
          </Button>
        ) : null}
      </div>

      {context.data.blocking_conditions.length > 0 ? (
        <div className="mt-4">
          <AgentDisclosure title={translate("agent.brief.blockers")}>
            <div className="flex flex-wrap gap-2">
              {context.data.blocking_conditions.map((condition) => (
                <Badge key={`${condition.code}-${condition.message}`} tone={severityTone(condition.severity)}>
                  {condition.message}
                </Badge>
              ))}
            </div>
          </AgentDisclosure>
        </div>
      ) : null}

    </Card>
  );
}
