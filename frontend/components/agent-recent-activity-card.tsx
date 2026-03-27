"use client";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/data-states";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { translate } from "@/lib/i18n/runtime";
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
import { workbenchSupportPanelClassName } from "@/lib/workbench-styles";
import type { AgentRecentActivityItem } from "@/lib/types";

function itemKindLabel(kind: AgentRecentActivityItem["item_kind"]) {
  return kind === "proposal" ? translate("agent.flow.proposal") : translate("agent.flow.approvalTicket");
}

type AgentRecentActivityCardProps = {
  items: AgentRecentActivityItem[];
  loading: boolean;
  error: string | null;
  eyebrow: string;
  title: string;
  summary: string;
  emptyTitle: string;
  emptyDescription: string;
  occurredAtLabel: string;
  statusLabel: string;
  rootTestId: string;
  getItemTestId: (item: AgentRecentActivityItem) => string;
};

export function AgentRecentActivityCard({
  items,
  loading,
  error,
  eyebrow,
  title,
  summary,
  emptyTitle,
  emptyDescription,
  occurredAtLabel,
  statusLabel,
  rootTestId,
  getItemTestId,
}: AgentRecentActivityCardProps) {
  if (loading && items.length === 0) {
    return (
      <PanelLoadingPlaceholder
        eyebrow={eyebrow}
        title={title}
        summary={summary}
        rows={2}
      />
    );
  }

  if (error && items.length === 0) {
    return <ErrorState message={error} />;
  }

  return (
    <Card className="p-4" data-testid={rootTestId}>
      <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{eyebrow}</p>
      <h3 className="mt-2 text-base font-semibold text-ink">{title}</h3>
      <p className="mt-2 text-sm leading-6 text-[#596270]">{summary}</p>

      <div className="mt-4 space-y-3">
        {items.length === 0 ? (
          <EmptyState title={emptyTitle} description={emptyDescription} />
        ) : (
          items.map((item) => (
            <div
              key={`${item.item_kind}-${item.activity_id}`}
              className={workbenchSupportPanelClassName("quiet", "p-4")}
              data-testid={getItemTestId(item)}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium text-ink">{item.summary}</p>
                    <Badge tone={item.item_kind === "proposal" ? "info" : "pending"}>{itemKindLabel(item.item_kind)}</Badge>
                  </div>
                  {item.detail ? <p className="mt-2 text-sm text-[#596270]">{item.detail}</p> : null}
                  <div className="mt-3 flex flex-wrap gap-3 text-xs text-[#6d7885]">
                    <span>{occurredAtLabel}: {formatDateTime(item.occurred_at)}</span>
                    <span>{statusLabel}: {formatStatusLabel(item.status)}</span>
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
