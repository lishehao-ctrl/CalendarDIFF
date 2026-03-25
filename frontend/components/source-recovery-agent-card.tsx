"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AgentMobileTriggerCard, AgentStepCard } from "@/components/agent-step-flow";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/data-states";
import { ApprovalTicketBar } from "@/components/approval-ticket-bar";
import { AgentProposalCard } from "@/components/agent-proposal-card";
import { Sheet, SheetContent, SheetDescription, SheetDismissButton, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  agentSourceContextCacheKey,
  cancelApprovalTicket,
  confirmApprovalTicket,
  createApprovalTicket,
  createSourceRecoveryProposal,
  getAgentSourceContext,
  getApprovalTicket,
} from "@/lib/api/agents";
import { deriveAgentSurfaceStage } from "@/lib/agent-ui";
import { withBasePath } from "@/lib/demo-mode";
import { translate } from "@/lib/i18n/runtime";
import { formatStatusLabel } from "@/lib/presenters";
import { useResponsiveTier } from "@/lib/use-responsive-tier";
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
  const { isMobile } = useResponsiveTier();
  const context = useApiResource<AgentSourceContext>(() => getAgentSourceContext(sourceId), [sourceId], null, {
    cacheKey: agentSourceContextCacheKey(sourceId),
  });
  const [proposal, setProposal] = useState<AgentProposal | null>(null);
  const [ticket, setTicket] = useState<ApprovalTicket | null>(null);
  const [proposalBusy, setProposalBusy] = useState(false);
  const [ticketBusy, setTicketBusy] = useState<"create" | "confirm" | "cancel" | "refresh" | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

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
        eyebrow={translate("agent.flow.suggestedPath")}
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
  const stage = deriveAgentSurfaceStage(proposal, ticket);
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
            <Button size="sm" onClick={() => void handleSuggestRecovery()} disabled={proposalBusy}>
              {proposalBusy ? translate("agent.suggestion.gettingSuggestion") : translate("agent.suggestion.getSuggestion")}
            </Button>
          ) : undefined
        }
      />

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
          executableMessage={translate("agent.suggestion.executableSource")}
          eyebrow={translate("agent.flow.proposal")}
          summaryOnly={Boolean(ticket)}
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
          eyebrow={ticket.status === "open" ? translate("agent.flow.approvalTicket") : translate("agent.flow.result")}
        />
      ) : null}
    </div>
  );

  if (isMobile) {
    return (
      <>
        <AgentMobileTriggerCard
          eyebrow={translate("agent.flow.suggestedPath")}
          title={context.data.recommended_next_action.label}
          summary={proposal ? proposal.summary : context.data.recommended_next_action.reason}
          badge={
            <Badge tone={riskTone(context.data.recommended_next_action.risk_level)}>
              {formatStatusLabel(context.data.recommended_next_action.risk_level)}
            </Badge>
          }
          action={
            <Button size="sm" variant="soft" onClick={() => setSheetOpen(true)}>
              {translate("agent.flow.openRecoveryHelper")}
            </Button>
          }
        />
        <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
          <SheetContent side="bottom" className="overflow-y-auto">
            <SheetHeader>
              <div>
                <SheetTitle className="text-xl">{translate("agent.suggestion.sourceAssistantTitle")}</SheetTitle>
                <SheetDescription>{translate("agent.suggestion.recommendedNextStep")}</SheetDescription>
              </div>
              <SheetDismissButton />
            </SheetHeader>
            <div className="mt-6">{content}</div>
          </SheetContent>
        </Sheet>
      </>
    );
  }

  return content;
}
