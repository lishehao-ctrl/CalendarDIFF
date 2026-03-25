"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AgentDisclosure, AgentStepCard } from "@/components/agent-step-flow";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/data-states";
import { ApprovalTicketBar } from "@/components/approval-ticket-bar";
import { AgentProposalCard } from "@/components/agent-proposal-card";
import {
  agentChangeContextCacheKey,
  cancelApprovalTicket,
  confirmApprovalTicket,
  createApprovalTicket,
  createChangeDecisionProposal,
  getAgentChangeContext,
  getApprovalTicket,
} from "@/lib/api/agents";
import { deriveAgentSurfaceStage } from "@/lib/agent-ui";
import { withBasePath } from "@/lib/demo-mode";
import { translate } from "@/lib/i18n/runtime";
import { formatStatusLabel } from "@/lib/presenters";
import type { AgentChangeContext, AgentProposal, ApprovalTicket } from "@/lib/types";
import { useApiResource } from "@/lib/use-api-resource";

function riskTone(risk: AgentChangeContext["recommended_next_action"]["risk_level"]) {
  switch (risk) {
    case "low":
      return "approved";
    case "high":
      return "error";
    default:
      return "pending";
  }
}

function isExecutableProposal(proposal: AgentProposal | null) {
  return proposal?.suggested_payload?.kind === "change_decision";
}

export function ChangeAgentCard({
  changeId,
  basePath = "",
}: {
  changeId: number;
  basePath?: string;
}) {
  const context = useApiResource<AgentChangeContext>(() => getAgentChangeContext(changeId), [changeId], null, {
    cacheKey: agentChangeContextCacheKey(changeId),
  });
  const [proposal, setProposal] = useState<AgentProposal | null>(null);
  const [ticket, setTicket] = useState<ApprovalTicket | null>(null);
  const [proposalBusy, setProposalBusy] = useState(false);
  const [ticketBusy, setTicketBusy] = useState<"create" | "confirm" | "cancel" | "refresh" | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  useEffect(() => {
    setProposal(null);
    setTicket(null);
    setProposalBusy(false);
    setTicketBusy(null);
    setBanner(null);
  }, [changeId]);

  async function handleGetSuggestion() {
    setProposalBusy(true);
    setBanner(null);
    try {
      const next = await createChangeDecisionProposal(changeId);
      setProposal(next);
    } catch (err) {
      setBanner(err instanceof Error ? err.message : translate("agent.suggestion.contextUnavailable"));
    } finally {
      setProposalBusy(false);
    }
  }

  async function handleCreateTicket() {
    if (!proposal) return;
    setTicketBusy("create");
    setBanner(null);
    try {
      const next = await createApprovalTicket(proposal.proposal_id);
      setTicket(next);
    } catch (err) {
      setBanner(err instanceof Error ? err.message : translate("agent.suggestion.notSafeToRunHere"));
    } finally {
      setTicketBusy(null);
    }
  }

  async function handleConfirm() {
    if (!ticket) return;
    setTicketBusy("confirm");
    setBanner(null);
    try {
      const next = await confirmApprovalTicket(ticket.ticket_id);
      setTicket(next);
    } catch (err) {
      setBanner(err instanceof Error ? err.message : translate("agent.ticket.failed"));
    } finally {
      setTicketBusy(null);
    }
  }

  async function handleCancel() {
    if (!ticket) return;
    setTicketBusy("cancel");
    setBanner(null);
    try {
      const next = await cancelApprovalTicket(ticket.ticket_id);
      setTicket(next);
    } catch (err) {
      setBanner(err instanceof Error ? err.message : translate("agent.ticket.failed"));
    } finally {
      setTicketBusy(null);
    }
  }

  async function handleRefreshTicket() {
    if (!ticket) return;
    setTicketBusy("refresh");
    setBanner(null);
    try {
      const next = await getApprovalTicket(ticket.ticket_id);
      setTicket(next);
    } catch (err) {
      setBanner(err instanceof Error ? err.message : translate("agent.suggestion.contextUnavailable"));
    } finally {
      setTicketBusy(null);
    }
  }

  if (context.loading && !context.data) {
    return (
      <PanelLoadingPlaceholder
        eyebrow={translate("agent.flow.suggestedPath")}
        title={translate("agent.suggestion.changeAssistantTitle")}
        rows={2}
      />
    );
  }

  if (context.error && !context.data) {
    return <ErrorState message={context.error} />;
  }

  if (!context.data) {
    return <EmptyState title={translate("agent.flow.suggestedPath")} description={translate("agent.suggestion.contextUnavailable")} />;
  }

  const executable = isExecutableProposal(proposal);
  const stage = deriveAgentSurfaceStage(proposal, ticket);
  const webOnlyAction =
    proposal?.suggested_payload?.kind === "web_only_change_edit_required" ? (
      <Button asChild size="sm" variant="ghost">
        <Link href={withBasePath(basePath, `/changes/${changeId}/canonical`)}>
          {translate("changes.editThenApprove")}
        </Link>
      </Button>
    ) : undefined;

  const content = (
    <div className="space-y-4">
      <AgentStepCard
        eyebrow={translate("agent.flow.suggestedPath")}
        title={context.data.recommended_next_action.label}
        summary={context.data.recommended_next_action.reason}
        badge={
          <Badge tone={riskTone(context.data.recommended_next_action.risk_level)}>
            {formatStatusLabel(context.data.recommended_next_action.risk_level)}
          </Badge>
        }
        state={stage === "brief" ? "active" : "complete"}
        actions={
          !proposal ? (
            <Button size="sm" onClick={() => void handleGetSuggestion()} disabled={proposalBusy}>
              {proposalBusy ? translate("agent.suggestion.gettingSuggestion") : translate("agent.suggestion.getSuggestion")}
            </Button>
          ) : undefined
        }
      >
        {context.data.blocking_conditions.length > 0 ? (
          <AgentDisclosure title={translate("agent.flow.reviewBlockers")}>
            <div className="flex flex-wrap gap-2">
              {context.data.blocking_conditions.map((condition) => (
                <Badge key={`${condition.code}-${condition.message}`} tone={condition.severity === "blocking" ? "error" : condition.severity === "warning" ? "pending" : "info"}>
                  {condition.message}
                </Badge>
              ))}
            </div>
          </AgentDisclosure>
        ) : null}
      </AgentStepCard>

      {banner ? (
        <Card className="border-[#efc4b5] bg-[#fff3ef] p-4">
          <p className="text-sm text-[#7f3d2a]">{banner}</p>
        </Card>
      ) : null}

      {proposal ? (
        <AgentProposalCard
          title={proposal.summary}
          proposal={proposal}
          executable={executable}
          blockingConditions={context.data.blocking_conditions}
          onCreateTicket={() => void handleCreateTicket()}
          creatingTicket={ticketBusy === "create"}
          webOnlyAction={webOnlyAction}
          executableMessage={translate("agent.suggestion.executableChange")}
          eyebrow={translate("agent.flow.proposal")}
          summaryOnly={Boolean(ticket)}
        />
      ) : null}

      {ticket ? (
        <ApprovalTicketBar
          ticket={ticket}
          busy={ticketBusy === "confirm" ? "confirm" : ticketBusy === "cancel" ? "cancel" : ticketBusy === "refresh" ? "refresh" : null}
          onConfirm={() => void handleConfirm()}
          onCancel={() => void handleCancel()}
          onRefresh={() => void handleRefreshTicket()}
          eyebrow={ticket.status === "open" ? translate("agent.flow.approvalTicket") : translate("agent.flow.result")}
        />
      ) : null}
    </div>
  );

  return content;
}
