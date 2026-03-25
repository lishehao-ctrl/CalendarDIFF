"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AgentDisclosure, AgentStepCard } from "@/components/agent-step-flow";
import { translate } from "@/lib/i18n/runtime";
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
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
  eyebrow,
  summaryOnly = false,
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
  eyebrow?: string;
  summaryOnly?: boolean;
}) {
  if (summaryOnly) {
    return (
      <AgentStepCard
        eyebrow={eyebrow || translate("agent.flow.proposal")}
        title={title}
        summary={proposal.reason}
        badge={<Badge tone={riskTone(proposal.risk_level)}>{formatStatusLabel(proposal.risk_level)}</Badge>}
        state="complete"
      />
    );
  }

  return (
    <AgentStepCard
      eyebrow={eyebrow || translate("agent.flow.proposal")}
      title={title}
      summary={proposal.reason}
      badge={<Badge tone={riskTone(proposal.risk_level)}>{formatStatusLabel(proposal.risk_level)}</Badge>}
      state="active"
      actions={
        <>
          {executable ? (
            <Button size="sm" onClick={onCreateTicket} disabled={creatingTicket}>
              {creatingTicket ? translate("agent.suggestion.creatingApprovalTicket") : translate("agent.suggestion.createApprovalTicket")}
            </Button>
          ) : null}
          {!executable && webOnlyAction ? webOnlyAction : null}
        </>
      }
    >
      <div className="grid gap-2 text-sm text-[#596270] md:grid-cols-2">
        <p>{translate("agent.suggestion.risk")}: {formatStatusLabel(proposal.risk_level)}</p>
        <p>{translate("common.status.created")}: {formatDateTime(proposal.created_at)}</p>
      </div>
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
      {blockingConditions.length > 0 ? (
        <div className="mt-4">
          <AgentDisclosure title={translate("agent.flow.reviewBlockers")}>
            <div className="flex flex-wrap gap-2">
              {blockingConditions.map((condition) => (
                <Badge key={`${condition.code}-${condition.message}`} tone={severityTone(condition.severity)}>
                  {condition.message}
                </Badge>
              ))}
            </div>
          </AgentDisclosure>
        </div>
      ) : null}
    </AgentStepCard>
  );
}
