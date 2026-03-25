"use client";

import { AgentStepCard } from "@/components/agent-step-flow";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

function actionLabel(actionType: ApprovalTicket["action_type"]) {
  switch (actionType) {
    case "run_source_sync":
      return translate("agent.actionLabels.runSourceSync");
    case "submit_change_decision":
    case "change_decision":
      return translate("agent.actionLabels.reviewChangeDecision");
    default:
      return actionType.replace(/_/g, " ");
  }
}

function resolveChangeDecisionLabel(ticket: ApprovalTicket) {
  const decision = ticket.payload?.decision;
  if (decision === "approve") {
    return translate("agent.actionLabels.approveChange");
  }
  if (decision === "reject") {
    return translate("agent.actionLabels.rejectChange");
  }
  return actionLabel(ticket.action_type);
}

function ticketActionLabel(ticket: ApprovalTicket) {
  if (ticket.action_type === "change_decision" || ticket.action_type === "submit_change_decision") {
    return resolveChangeDecisionLabel(ticket);
  }
  switch (ticket.action_type) {
    case "run_source_sync":
      return translate("agent.actionLabels.runSourceSync");
    default:
      return actionLabel(ticket.action_type);
  }
}

export function ApprovalTicketBar({
  ticket,
  busy,
  onConfirm,
  onCancel,
  onRefresh,
  eyebrow,
}: {
  ticket: ApprovalTicket;
  busy: "confirm" | "cancel" | "refresh" | null;
  onConfirm: () => void;
  onCancel: () => void;
  onRefresh: () => void;
  eyebrow?: string;
}) {
  return (
    <AgentStepCard
      eyebrow={eyebrow || (ticket.status === "open" ? translate("agent.flow.approvalTicket") : translate("agent.flow.result"))}
      title={ticketActionLabel(ticket)}
      badge={<Badge tone={statusTone(ticket.status)}>{statusLabel(ticket.status)}</Badge>}
      state={ticket.status === "open" ? "active" : "terminal"}
      actions={
        ticket.status === "open" ? (
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
        )
      }
    >
      <div className="grid gap-2 text-sm text-[#596270] md:grid-cols-2">
        <p>{translate("agent.ticket.createdAt")}: {formatDateTime(ticket.created_at)}</p>
        <p>{translate("agent.ticket.expiresAt")}: {formatDateTime(ticket.expires_at, translate("common.labels.notAvailable"))}</p>
        {ticket.executed_at ? <p>{translate("agent.ticket.executedAt")}: {formatDateTime(ticket.executed_at)}</p> : null}
        {ticket.canceled_at ? <p>{translate("agent.ticket.canceledAt")}: {formatDateTime(ticket.canceled_at)}</p> : null}
      </div>
      {ticket.status !== "open" ? (
        <p className="mt-4 text-xs leading-5 text-[#6d7885]">{translate("agent.ticket.finalStateVisible")}</p>
      ) : null}
    </AgentStepCard>
  );
}
