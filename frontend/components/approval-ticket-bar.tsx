"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { translate } from "@/lib/i18n/runtime";
import { formatDateTime } from "@/lib/presenters";
import type { ApprovalTicket } from "@/lib/types";

function statusTone(status: ApprovalTicket["status"]) {
  switch (status) {
    case "executed":
      return "approved";
    case "failed":
      return "error";
    case "expired":
      return "pending";
    case "canceled":
      return "info";
    default:
      return "pending";
  }
}

function statusLabel(status: ApprovalTicket["status"]) {
  switch (status) {
    case "executed":
      return translate("agent.ticket.executed");
    case "canceled":
      return translate("agent.ticket.canceled");
    case "expired":
      return translate("agent.ticket.expired");
    case "failed":
      return translate("agent.ticket.failed");
    default:
      return translate("agent.ticket.open");
  }
}

export function ApprovalTicketBar({
  ticket,
  busy,
  onConfirm,
  onCancel,
  onRefresh,
}: {
  ticket: ApprovalTicket;
  busy: "confirm" | "cancel" | "refresh" | null;
  onConfirm: () => void;
  onCancel: () => void;
  onRefresh: () => void;
}) {
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.ticket.eyebrow")}</p>
          <p className="mt-2 text-sm font-medium text-ink">{ticket.action_type}</p>
        </div>
        <Badge tone={statusTone(ticket.status)}>{statusLabel(ticket.status)}</Badge>
      </div>
      <div className="mt-4 grid gap-2 text-sm text-[#596270] md:grid-cols-2">
        <p>{translate("agent.ticket.createdAt")}: {formatDateTime(ticket.created_at)}</p>
        <p>{translate("agent.ticket.expiresAt")}: {formatDateTime(ticket.expires_at, translate("common.labels.notAvailable"))}</p>
        {ticket.executed_at ? <p>{translate("agent.ticket.executedAt")}: {formatDateTime(ticket.executed_at)}</p> : null}
        {ticket.canceled_at ? <p>{translate("agent.ticket.canceledAt")}: {formatDateTime(ticket.canceled_at)}</p> : null}
      </div>
      <div className="mt-4 flex flex-wrap gap-3">
        {ticket.status === "open" ? (
          <>
            <Button size="sm" onClick={onConfirm} disabled={busy !== null}>
              {busy === "confirm" ? translate("agent.ticket.confirming") : translate("agent.ticket.confirmNow")}
            </Button>
            <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy !== null}>
              {busy === "cancel" ? translate("agent.ticket.canceling") : translate("agent.ticket.cancel")}
            </Button>
          </>
        ) : (
          <Button size="sm" variant="ghost" onClick={onRefresh} disabled={busy !== null}>
            {translate("agent.suggestion.refreshStatus")}
          </Button>
        )}
      </div>
      {ticket.status !== "open" ? (
        <p className="mt-4 text-xs leading-5 text-[#6d7885]">{translate("agent.ticket.finalStateVisible")}</p>
      ) : null}
    </Card>
  );
}
