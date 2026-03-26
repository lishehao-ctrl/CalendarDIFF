"use client";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/data-states";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { agentRecentActivityCacheKey, getRecentAgentActivity } from "@/lib/api/agents";
import { translate } from "@/lib/i18n/runtime";
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
import { useApiResource } from "@/lib/use-api-resource";
import { workbenchSupportPanelClassName } from "@/lib/workbench-styles";
import type { AgentRecentActivityItem, AgentRecentActivityResponse } from "@/lib/types";

function itemKindLabel(kind: AgentRecentActivityItem["item_kind"]) {
  return kind === "proposal" ? translate("agent.flow.proposal") : translate("agent.flow.approvalTicket");
}

function itemTestId(item: AgentRecentActivityItem) {
  if (item.item_kind === "ticket" && item.ticket_id) {
    return `settings-agent-activity-item-ticket-${item.ticket_id}`;
  }
  if (item.item_kind === "proposal" && item.proposal_id != null) {
    return `settings-agent-activity-item-proposal-${item.proposal_id}`;
  }
  return `settings-agent-activity-item-${item.item_kind}-${item.activity_id}`;
}

export function SettingsAgentActivityCard() {
  const activity = useApiResource<AgentRecentActivityResponse>(() => getRecentAgentActivity(8), [], null, {
    cacheKey: agentRecentActivityCacheKey(8),
  });

  if (activity.loading && !activity.data) {
    return (
      <PanelLoadingPlaceholder
        eyebrow={translate("settings.agentActivity.eyebrow")}
        title={translate("settings.agentActivity.title")}
        summary={translate("settings.agentActivity.summary")}
        rows={2}
      />
    );
  }

  if (activity.error && !activity.data) {
    return <ErrorState message={activity.error} />;
  }

  const items = activity.data?.items || [];

  return (
    <Card className="p-4" data-testid="settings-agent-activity-card">
      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("settings.agentActivity.eyebrow")}</p>
      <h3 className="mt-2 text-base font-semibold text-ink">{translate("settings.agentActivity.title")}</h3>
      <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("settings.agentActivity.summary")}</p>

      <div className="mt-4 space-y-3">
        {items.length === 0 ? (
          <EmptyState
            title={translate("settings.agentActivity.emptyTitle")}
            description={translate("settings.agentActivity.emptyDescription")}
          />
        ) : (
          items.map((item) => (
            <div
              key={`${item.item_kind}-${item.activity_id}`}
              className={workbenchSupportPanelClassName("quiet", "p-4")}
              data-testid={itemTestId(item)}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium text-ink">{item.summary}</p>
                    <Badge tone={item.item_kind === "proposal" ? "info" : "pending"}>{itemKindLabel(item.item_kind)}</Badge>
                  </div>
                  {item.detail ? <p className="mt-2 text-sm text-[#596270]">{item.detail}</p> : null}
                  <div className="mt-3 flex flex-wrap gap-3 text-xs text-[#6d7885]">
                    <span>{translate("settings.agentActivity.occurredAt")}: {formatDateTime(item.occurred_at)}</span>
                    <span>{translate("settings.agentActivity.status")}: {formatStatusLabel(item.status)}</span>
                  </div>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}
