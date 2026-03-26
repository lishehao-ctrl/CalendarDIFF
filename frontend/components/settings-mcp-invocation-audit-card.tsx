"use client";

import { useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/data-states";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { getMcpInvocations, settingsMcpInvocationsCacheKey } from "@/lib/api/settings";
import { translate } from "@/lib/i18n/runtime";
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
import { useApiResource } from "@/lib/use-api-resource";
import { workbenchSupportPanelClassName } from "@/lib/workbench-styles";
import type { McpToolInvocation } from "@/lib/types";

function statusTone(status: McpToolInvocation["status"]) {
  switch (status) {
    case "succeeded":
      return "approved";
    case "failed":
      return "error";
    case "started":
      return "pending";
    default:
      return "info";
  }
}

function humanizeIdentifier(value: string | null | undefined) {
  if (!value) {
    return translate("common.labels.notAvailable");
  }
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function targetLabel(item: McpToolInvocation) {
  const targetKind = item.target_kind || (typeof item.output_summary.target_kind === "string" ? item.output_summary.target_kind : null);
  const targetId = item.target_id || (typeof item.output_summary.target_id === "string" ? item.output_summary.target_id : null);
  const translatedTargetKind = targetKind ? translate(`settings.mcpAudit.targetKinds.${targetKind}`) : "";
  const normalizedTargetKind = translatedTargetKind === `settings.mcpAudit.targetKinds.${targetKind}` ? humanizeIdentifier(targetKind) : translatedTargetKind;

  if (normalizedTargetKind && targetId) {
    return /^\d+$/.test(targetId) ? `${normalizedTargetKind} #${targetId}` : `${normalizedTargetKind} ${targetId}`;
  }
  if (normalizedTargetKind) {
    return normalizedTargetKind;
  }
  if (targetId) {
    return targetId;
  }
  return translate("settings.mcpAudit.noTarget");
}

function ActivityFact({ label, value }: { label: string; value: string }) {
  return (
    <div className={workbenchSupportPanelClassName("default", "p-3")}>
      <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{label}</p>
      <p className="mt-2 text-sm font-medium text-ink">{value}</p>
    </div>
  );
}

export function SettingsMcpInvocationAuditCard() {
  const activity = useApiResource<McpToolInvocation[]>(() => getMcpInvocations(10), [], [], {
    cacheKey: settingsMcpInvocationsCacheKey(10),
  });

  const stats = useMemo(() => {
    const items = activity.data || [];
    return {
      total: items.length,
      succeeded: items.filter((item) => item.status === "succeeded").length,
      failed: items.filter((item) => item.status === "failed").length,
      latest: items[0]?.created_at || null,
    };
  }, [activity.data]);

  if (activity.loading && !activity.data?.length) {
    return (
      <PanelLoadingPlaceholder
        eyebrow={translate("settings.mcpAudit.eyebrow")}
        title={translate("settings.mcpAudit.title")}
        summary={translate("settings.mcpAudit.summary")}
        rows={2}
      />
    );
  }

  if (activity.error && !activity.data?.length) {
    return <ErrorState message={activity.error} />;
  }

  const items = activity.data || [];

  return (
    <Card className="p-4" data-testid="settings-mcp-invocation-audit-card">
      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("settings.mcpAudit.eyebrow")}</p>
      <h3 className="mt-2 text-base font-semibold text-ink">{translate("settings.mcpAudit.title")}</h3>
      <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("settings.mcpAudit.summary")}</p>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <ActivityFact label={translate("settings.mcpAudit.totalCalls")} value={String(stats.total)} />
        <ActivityFact label={translate("settings.mcpAudit.succeeded")} value={String(stats.succeeded)} />
        <ActivityFact label={translate("settings.mcpAudit.failed")} value={String(stats.failed)} />
        <ActivityFact
          label={translate("settings.mcpAudit.lastSeen")}
          value={stats.latest ? formatDateTime(stats.latest) : translate("settings.mcpAudit.noRecentCall")}
        />
      </div>

      <div className="mt-4 space-y-3">
        {items.length === 0 ? (
          <EmptyState
            title={translate("settings.mcpAudit.emptyTitle")}
            description={translate("settings.mcpAudit.emptyDescription")}
          />
        ) : (
          <>
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("settings.mcpAudit.recentList")}</p>
            {items.map((item) => (
              <div
                key={item.invocation_id}
                className={workbenchSupportPanelClassName("quiet", "p-4")}
                data-testid={`settings-mcp-invocation-${item.invocation_id}`}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-medium text-ink">{targetLabel(item)}</p>
                      <Badge tone={statusTone(item.status)}>{formatStatusLabel(item.status)}</Badge>
                    </div>
                    <div className="mt-3 grid gap-2 text-sm text-[#596270]">
                      <p>{translate("settings.mcpAudit.tool")}: <span className="font-mono text-[12px] text-[#314051]">{item.tool_name}</span></p>
                      <p>{translate("settings.mcpAudit.occurredAt")}: {formatDateTime(item.created_at)}</p>
                      <p>
                        {translate("settings.mcpAudit.completedAt")}: {item.completed_at ? formatDateTime(item.completed_at) : translate("settings.mcpAudit.inProgress")}
                      </p>
                    </div>
                    {item.error_text ? <p className="mt-3 text-sm leading-6 text-[#7f3d2a]">{item.error_text}</p> : null}
                  </div>
                </div>
              </div>
            ))}
          </>
        )}
      </div>
    </Card>
  );
}
