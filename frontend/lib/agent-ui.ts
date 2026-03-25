import type { AgentProposal, ApprovalTicket } from "@/lib/types";

export type AgentSurfaceStage = "brief" | "proposal" | "ticket";

export function deriveAgentSurfaceStage(proposal: AgentProposal | null, ticket: ApprovalTicket | null): AgentSurfaceStage {
  if (ticket) {
    return "ticket";
  }
  if (proposal) {
    return "proposal";
  }
  return "brief";
}

export function hasTerminalTicketStatus(ticket: ApprovalTicket | null) {
  return Boolean(ticket && ticket.status !== "open");
}
