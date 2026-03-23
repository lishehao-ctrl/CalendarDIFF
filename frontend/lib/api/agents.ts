import { apiGet, apiPost } from "@/lib/api/client";
import type {
  AgentChangeContext,
  AgentProposal,
  AgentSourceContext,
  AgentWorkspaceContext,
  ApprovalTicket,
} from "@/lib/types";

export function agentWorkspaceContextCacheKey() {
  return "agent:context:workspace";
}

export function agentChangeContextCacheKey(changeId: number) {
  return `agent:context:change:${changeId}`;
}

export function agentSourceContextCacheKey(sourceId: number) {
  return `agent:context:source:${sourceId}`;
}

export function agentProposalCacheKey(proposalId: number) {
  return `agent:proposal:${proposalId}`;
}

export function approvalTicketCacheKey(ticketId: string) {
  return `agent:approval-ticket:${ticketId}`;
}

export async function getAgentWorkspaceContext() {
  return apiGet<AgentWorkspaceContext>("/agent/context/workspace");
}

export async function getAgentChangeContext(changeId: number) {
  return apiGet<AgentChangeContext>(`/agent/context/changes/${changeId}`);
}

export async function getAgentSourceContext(sourceId: number) {
  return apiGet<AgentSourceContext>(`/agent/context/sources/${sourceId}`);
}

export async function createChangeDecisionProposal(changeId: number) {
  return apiPost<AgentProposal>("/agent/proposals/change-decision", { change_id: changeId });
}

export async function createSourceRecoveryProposal(sourceId: number) {
  return apiPost<AgentProposal>("/agent/proposals/source-recovery", { source_id: sourceId });
}

export async function getAgentProposal(proposalId: number) {
  return apiGet<AgentProposal>(`/agent/proposals/${proposalId}`);
}

export async function createApprovalTicket(proposalId: number, channel = "web") {
  return apiPost<ApprovalTicket>("/agent/approval-tickets", { proposal_id: proposalId, channel });
}

export async function getApprovalTicket(ticketId: string) {
  return apiGet<ApprovalTicket>(`/agent/approval-tickets/${encodeURIComponent(ticketId)}`);
}

export async function confirmApprovalTicket(ticketId: string) {
  return apiPost<ApprovalTicket>(`/agent/approval-tickets/${encodeURIComponent(ticketId)}/confirm`, {});
}

export async function cancelApprovalTicket(ticketId: string) {
  return apiPost<ApprovalTicket>(`/agent/approval-tickets/${encodeURIComponent(ticketId)}/cancel`, {});
}
