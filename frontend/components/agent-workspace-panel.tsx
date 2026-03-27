"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowRight } from "lucide-react";
import { AgentCommandPanel } from "@/components/agent-command-panel";
import { AgentDisclosure } from "@/components/agent-step-flow";
import { AgentRecentActivityCard } from "@/components/agent-recent-activity-card";
import { buildContextualAgentCommandSuggestions, buildPendingChangePrompt, buildRecommendedActionPrompt, buildSourceBlockerPrompt, buildStaticAgentCommandSuggestions } from "@/lib/agent-command-suggestions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/data-states";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { agentRecentActivityCacheKey, agentWorkspaceContextCacheKey, getAgentWorkspaceContext, getRecentAgentActivity } from "@/lib/api/agents";
import { agentLaneHref } from "@/lib/agent-lane";
import { withBasePath } from "@/lib/demo-mode";
import { translate } from "@/lib/i18n/runtime";
import { formatDateTime, formatStatusLabel, summarizeChange } from "@/lib/presenters";
import { useResponsiveTier } from "@/lib/use-responsive-tier";
import { useApiResource } from "@/lib/use-api-resource";
import { workbenchQueueRowClassName, workbenchSupportPanelClassName } from "@/lib/workbench-styles";
import type { AgentRecentActivityItem, AgentRecentActivityResponse, AgentWorkspaceContext } from "@/lib/types";

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

function severityTone(severity: AgentWorkspaceContext["blocking_conditions"][number]["severity"]) {
  switch (severity) {
    case "blocking":
      return "error";
    case "warning":
      return "pending";
    default:
      return "info";
  }
}

function hasSourceBlocker(blockingConditions: AgentWorkspaceContext["blocking_conditions"]) {
  return blockingConditions.some((condition) => condition.code.includes("source"));
}

function activityItemTestId(item: AgentRecentActivityItem) {
  if (item.item_kind === "ticket" && item.ticket_id) {
    return `agent-workspace-activity-item-ticket-${item.ticket_id}`;
  }
  if (item.item_kind === "proposal" && item.proposal_id != null) {
    return `agent-workspace-activity-item-proposal-${item.proposal_id}`;
  }
  return `agent-workspace-activity-item-${item.item_kind}-${item.activity_id}`;
}

export function AgentWorkspacePanel({ basePath = "" }: { basePath?: string }) {
  const { isDesktop, isTabletWide } = useResponsiveTier();
  const [commandDraft, setCommandDraft] = useState("");
  const [focusRequestToken, setFocusRequestToken] = useState(0);
  const context = useApiResource<AgentWorkspaceContext>(() => getAgentWorkspaceContext(), [], null, {
    cacheKey: agentWorkspaceContextCacheKey(),
  });
  const activity = useApiResource<AgentRecentActivityResponse>(() => getRecentAgentActivity(8), [], null, {
    cacheKey: agentRecentActivityCacheKey(8),
  });

  function seedCommandPrompt(prompt: string) {
    setCommandDraft(prompt);
    setFocusRequestToken((current) => current + 1);
  }

  const commandSuggestions = useMemo(
    () => (context.data
      ? [
          ...buildStaticAgentCommandSuggestions(),
          ...buildContextualAgentCommandSuggestions(context.data),
        ]
      : buildStaticAgentCommandSuggestions()),
    [context.data],
  );

  if (context.loading && !context.data) {
    return (
      <PanelLoadingPlaceholder
        eyebrow={translate("agent.brief.eyebrow")}
        title={translate("agentPage.title")}
        summary={translate("agentPage.summary")}
        rows={3}
      />
    );
  }

  if (context.error && !context.data) {
    return <ErrorState message={context.error} />;
  }

  if (!context.data) {
    return <EmptyState title={translate("agentPage.title")} description={translate("agent.brief.unavailable")} />;
  }

  const recommendedActionPrompt = buildRecommendedActionPrompt(context.data);
  const sourceBlockerPrompt = hasSourceBlocker(context.data.blocking_conditions)
    ? buildSourceBlockerPrompt(context.data.blocking_conditions)
    : null;
  const recommendedLaneHref = withBasePath(basePath, agentLaneHref(context.data.recommended_next_action.lane));
  const showSourcesCta = hasSourceBlocker(context.data.blocking_conditions) && context.data.recommended_next_action.lane !== "sources";
  const topPendingChanges = context.data.top_pending_changes.slice(0, 4);

  async function refreshAgentSurfaces() {
    await Promise.all([
      context.refresh({ background: Boolean(context.data), force: true }),
      activity.refresh({ background: Boolean(activity.data), force: true }),
    ]);
  }

  const nextStepCard = (
    <Card
      className="animate-surface-enter overflow-hidden border-cobalt/15 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.1),transparent_38%),linear-gradient(180deg,rgba(255,255,255,0.98),rgba(246,249,255,0.94))] p-5 shadow-[0_18px_38px_rgba(20,32,44,0.08)]"
      data-testid="agent-workspace-next-step-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-3xl">
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.brief.eyebrow")}</p>
          <h2 className="mt-2 text-lg font-semibold text-ink">{context.data.recommended_next_action.label}</h2>
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
        <Button size="sm" variant="soft" onClick={() => seedCommandPrompt(recommendedActionPrompt)}>
          {translate("agent.command.useInAssistant")}
        </Button>
        {showSourcesCta ? (
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
            {sourceBlockerPrompt ? (
              <div className="mt-3">
                <Button size="sm" variant="soft" onClick={() => seedCommandPrompt(sourceBlockerPrompt)}>
                  {translate("agent.command.askAssistantInspectSources")}
                </Button>
              </div>
            ) : null}
          </AgentDisclosure>
        </div>
      ) : null}
    </Card>
  );

  const pendingChangesCard = (
    <Card
      className="animate-surface-enter animate-surface-delay-1 p-4 shadow-[0_12px_28px_rgba(20,32,44,0.05)]"
      data-testid="agent-workspace-top-pending-card"
    >
      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.brief.topChanges")}</p>
      <h3 className="mt-2 text-base font-semibold text-ink">{translate("overview.cards.changes.reviewTitle")}</h3>
      <div className="mt-4 space-y-3">
        {topPendingChanges.length === 0 ? (
          <div className={workbenchSupportPanelClassName("quiet", "p-4")}>
            <p className="text-sm font-medium text-ink">{translate("overview.cards.changes.quiet")}</p>
            <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("overview.cards.changes.noReplayWaiting")}</p>
          </div>
        ) : (
          topPendingChanges.map((change) => {
            const summary = summarizeChange(change);
            const changePrompt = buildPendingChangePrompt(change);
            return (
              <div
                key={change.id}
                className={workbenchQueueRowClassName({
                  className: "animate-list-enter space-y-3 px-4 py-3",
                })}
                data-testid={`agent-workspace-top-change-${change.id}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink">{summary.title}</p>
                    <p className="mt-1 text-xs text-[#6d7885]">{formatDateTime(change.detected_at)}</p>
                  </div>
                  <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-[#6d7885]" />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button asChild size="sm">
                    <Link href={withBasePath(basePath, `/changes?focus=${change.id}`)}>
                      {translate("agent.command.openChange")}
                    </Link>
                  </Button>
                  <Button size="sm" variant="soft" onClick={() => seedCommandPrompt(changePrompt)}>
                    {translate("agent.command.askAssistant")}
                  </Button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </Card>
  );

  const activityCard = (
    <AgentRecentActivityCard
      items={activity.data?.items || []}
      loading={activity.loading}
      error={activity.error}
      eyebrow={translate("agent.activity.eyebrow")}
      title={translate("agent.activity.title")}
      summary={translate("agent.activity.summary")}
      emptyTitle={translate("agent.activity.emptyTitle")}
      emptyDescription={translate("agent.activity.emptyDescription")}
      occurredAtLabel={translate("settings.agentActivity.occurredAt")}
      statusLabel={translate("settings.agentActivity.status")}
      rootTestId="agent-workspace-activity-card"
      getItemTestId={activityItemTestId}
      className="animate-surface-enter animate-surface-delay-2 shadow-[0_12px_28px_rgba(20,32,44,0.05)]"
    />
  );

  const commandStudio = (
    <div className="animate-surface-enter">
      <AgentCommandPanel
        draft={commandDraft}
        onDraftChange={setCommandDraft}
        suggestions={commandSuggestions}
        focusRequestToken={focusRequestToken}
        onRunUpdated={() => void refreshAgentSurfaces()}
        basePath={basePath}
      />
    </div>
  );

  return (
    <div className="space-y-5">
      {nextStepCard}
      {commandStudio}
      <div className={isDesktop || isTabletWide ? "grid gap-4 xl:grid-cols-2" : "space-y-4"}>
        <AgentDisclosure title={translate("agent.brief.topChanges")}>
          {pendingChangesCard}
        </AgentDisclosure>
        <AgentDisclosure title={translate("agent.activity.title")}>
          {activityCard}
        </AgentDisclosure>
      </div>
    </div>
  );
}
