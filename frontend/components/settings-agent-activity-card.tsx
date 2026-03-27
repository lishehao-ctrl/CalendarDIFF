"use client";

import { AgentRecentActivityCard } from "@/components/agent-recent-activity-card";
import { agentRecentActivityCacheKey, getRecentAgentActivity } from "@/lib/api/agents";
import { translate } from "@/lib/i18n/runtime";
import { useApiResource } from "@/lib/use-api-resource";
import type { AgentRecentActivityItem, AgentRecentActivityResponse } from "@/lib/types";

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

  return (
    <AgentRecentActivityCard
      items={activity.data?.items || []}
      loading={activity.loading}
      error={activity.error}
      eyebrow={translate("settings.agentActivity.eyebrow")}
      title={translate("settings.agentActivity.title")}
      summary={translate("settings.agentActivity.summary")}
      emptyTitle={translate("settings.agentActivity.emptyTitle")}
      emptyDescription={translate("settings.agentActivity.emptyDescription")}
      occurredAtLabel={translate("settings.agentActivity.occurredAt")}
      statusLabel={translate("settings.agentActivity.status")}
      rootTestId="settings-agent-activity-card"
      getItemTestId={itemTestId}
    />
  );
}
