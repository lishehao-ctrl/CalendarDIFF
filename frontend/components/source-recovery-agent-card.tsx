"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/data-states";
import { ApprovalTicketBar } from "@/components/approval-ticket-bar";
import { AgentProposalCard } from "@/components/agent-proposal-card";
import {
  agentSourceContextCacheKey,
  cancelApprovalTicket,
  confirmApprovalTicket,
  createApprovalTicket,
  createSourceRecoveryProposal,
  getAgentSourceContext,
  getApprovalTicket,
} from "@/lib/api/agents";
import { withBasePath } from "@/lib/demo-mode";
import { translate } from "@/lib/i18n/runtime";
import type { AgentProposal, AgentSourceContext, ApprovalTicket } from "@/lib/types";
import { useApiResource } from "@/lib/use-api-resource";

function riskTone(risk: AgentSourceContext["recommended_next_action"]["risk_level"]) {
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
  return proposal?.suggested_payload?.kind === "run_source_sync";
}

function webOnlyHref(proposal: AgentProposal, sourceId: number, basePath: string) {
  const kind = proposal.suggested_payload?.kind;
  if (kind === "reconnect_source" || kind === "update_source_settings") {
    return withBasePath(
      basePath,
      proposal.suggested_payload?.provider === "gmail" ? "/sources/connect/gmail" : "/sources/connect/canvas-ics",
    );
  }
  return withBasePath(basePath, `/sources/${sourceId}`);
}

export function SourceRecoveryAgentCard({
  sourceId,
  basePath = "",
}: {
  sourceId: number;
  basePath?: string;
}) {
  const context = useApiResource<AgentSourceContext>(() => getAgentSourceContext(sourceId), [sourceId], null, {
    cacheKey: agentSourceContextCacheKey(sourceId),
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
  }, [sourceId]);

  async function handleSuggestRecovery() {
    setProposalBusy(true);
    setBanner(null);
    try {
      const next = await createSourceRecoveryProposal(sourceId);
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
        eyebrow={translate("agent.suggestion.eyebrow")}
        title={translate("agent.suggestion.sourceAssistantTitle")}
        rows={2}
      />
    );
  }
  if (context.error && !context.data) {
    return <ErrorState message={context.error} />;
  }
  if (!context.data) {
    return <EmptyState title={translate("agent.suggestion.sourceAssistantTitle")} description={translate("agent.suggestion.contextUnavailable")} />;
  }

  const executable = isExecutableProposal(proposal);

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("agent.suggestion.eyebrow")}</p>
            <h3 className="mt-2 text-lg font-semibold text-ink">{translate("agent.suggestion.sourceAssistantTitle")}</h3>
          </div>
          <Badge tone={riskTone(context.data.recommended_next_action.risk_level)}>
            {context.data.recommended_next_action.risk_level}
          </Badge>
        </div>
        <div className="mt-4 rounded-[1rem] border border-line/80 bg-white/72 p-4">
          <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("agent.suggestion.recommendedNextStep")}</p>
          <p className="mt-2 text-sm font-medium text-ink">{context.data.recommended_next_action.label}</p>
          <p className="mt-2 text-sm leading-6 text-[#596270]">{context.data.recommended_next_action.reason}</p>
        </div>
        {context.data.blocking_conditions.length > 0 ? (
          <div className="mt-4 flex flex-wrap gap-2">
            {context.data.blocking_conditions.map((condition) => (
              <Badge key={`${condition.code}-${condition.message}`} tone={condition.severity === "blocking" ? "error" : condition.severity === "warning" ? "pending" : "info"}>
                {condition.message}
              </Badge>
            ))}
          </div>
        ) : null}
        <div className="mt-4">
          <Button size="sm" onClick={() => void handleSuggestRecovery()} disabled={proposalBusy}>
            {proposalBusy ? translate("agent.suggestion.gettingSuggestion") : translate("agent.suggestion.getSuggestion")}
          </Button>
        </div>
      </Card>

      {banner ? (
        <Card className="border-[#efc4b5] bg-[#fff3ef] p-4">
          <p className="text-sm text-[#7f3d2a]">{banner}</p>
        </Card>
      ) : null}

      {proposal ? (
        <AgentProposalCard
          title={translate("agent.suggestion.sourceAssistantTitle")}
          proposal={proposal}
          executable={executable}
          blockingConditions={context.data.blocking_conditions}
          onCreateTicket={() => void handleCreateTicket()}
          creatingTicket={ticketBusy === "create"}
          executableMessage={translate("agent.suggestion.executableSource")}
          webOnlyAction={
            !executable ? (
              <Button asChild size="sm" variant="ghost">
                <Link href={webOnlyHref(proposal, sourceId, basePath)}>{translate("agent.suggestion.openConnectionFlow")}</Link>
              </Button>
            ) : undefined
          }
        />
      ) : null}

      {ticket ? (
        <ApprovalTicketBar
          ticket={ticket}
          busy={ticketBusy === "confirm" ? "confirm" : ticketBusy === "cancel" ? "cancel" : ticketBusy === "refresh" ? "refresh" : null}
          onConfirm={() => void handleConfirm()}
          onCancel={() => void handleCancel()}
          onRefresh={() => void handleRefreshTicket()}
        />
      ) : null}
    </div>
  );
}
