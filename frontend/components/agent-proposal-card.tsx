"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { translate } from "@/lib/i18n/runtime";
import { formatDateTime } from "@/lib/presenters";
import type { AgentProposal, AgentBlockingCondition } from "@/lib/types";

function riskTone(risk: AgentProposal["risk_level"]) {
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

export function AgentProposalCard({
  title,
  proposal,
  executable,
  blockingConditions,
  onCreateTicket,
  creatingTicket,
  webOnlyAction,
  executableMessage,
  webOnlyMessage,
}: {
  title: string;
  proposal: AgentProposal;
  executable: boolean;
  blockingConditions: AgentBlockingCondition[];
  onCreateTicket: () => void;
  creatingTicket: boolean;
  webOnlyAction?: React.ReactNode;
  executableMessage?: string;
  webOnlyMessage?: string;
}) {
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.suggestion.eyebrow")}</p>
          <h3 className="mt-2 text-lg font-semibold text-ink">{title}</h3>
        </div>
        <Badge tone={riskTone(proposal.risk_level)}>{proposal.risk_level}</Badge>
      </div>
      <p className="mt-4 text-sm font-medium text-ink">{proposal.summary}</p>
      <p className="mt-2 text-sm leading-6 text-[#596270]">{proposal.reason}</p>
      <div className="mt-4 grid gap-2 text-sm text-[#596270] md:grid-cols-2">
        <p>{translate("agent.suggestion.risk")}: {proposal.risk_level}</p>
        <p>{translate("common.status.created")}: {formatDateTime(proposal.created_at)}</p>
      </div>
      {blockingConditions.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {blockingConditions.map((condition) => (
            <Badge key={`${condition.code}-${condition.message}`} tone={severityTone(condition.severity)}>
              {condition.message}
            </Badge>
          ))}
        </div>
      ) : null}
      <div className="mt-4 rounded-[1rem] border border-line/80 bg-white/72 p-4 text-sm text-[#314051]">
        <p className="font-medium text-ink">
          {executable ? translate("agent.suggestion.readyToConfirm") : translate("agent.suggestion.needsWebReview")}
        </p>
        <p className="mt-2 leading-6">
          {executable
            ? executableMessage || translate("agent.suggestion.executableChange")
            : webOnlyMessage || translate("agent.suggestion.explanationOnly")}
        </p>
      </div>
      <div className="mt-4 flex flex-wrap gap-3">
        {executable ? (
          <Button size="sm" onClick={onCreateTicket} disabled={creatingTicket}>
            {creatingTicket ? translate("agent.suggestion.creatingApprovalTicket") : translate("agent.suggestion.createApprovalTicket")}
          </Button>
        ) : null}
        {!executable && webOnlyAction ? webOnlyAction : null}
      </div>
    </Card>
  );
}
