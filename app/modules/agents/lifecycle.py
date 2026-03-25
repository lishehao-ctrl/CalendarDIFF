from __future__ import annotations

from typing import Literal

from app.db.models.agents import ApprovalTicket, ApprovalTicketStatus, AgentProposal, AgentProposalStatus

ProposalExecutionMode = Literal["approval_ticket_required", "web_only"]


def proposal_execution_mode(row: AgentProposal) -> ProposalExecutionMode:
    kind = str((row.payload_json or {}).get("kind") or "")
    if kind in {"change_decision", "run_source_sync", "family_relink_commit", "label_learning_add_alias_commit", "proposal_edit_commit"}:
        return "approval_ticket_required"
    return "web_only"


def proposal_execution_mode_code(row: AgentProposal) -> str:
    mode = proposal_execution_mode(row)
    return f"agents.proposal.execution_mode.{mode}"


def proposal_lifecycle_code(row: AgentProposal) -> str:
    return f"agents.proposal.lifecycle.{row.status.value}"


def proposal_next_step_code(row: AgentProposal) -> str:
    if row.status == AgentProposalStatus.OPEN:
        mode = proposal_execution_mode(row)
        if mode == "approval_ticket_required":
            return "agents.proposal.next_step.create_ticket"
        return "agents.proposal.next_step.open_web_flow"
    if row.status == AgentProposalStatus.ACCEPTED:
        return "agents.proposal.next_step.completed"
    if row.status == AgentProposalStatus.REJECTED:
        return "agents.proposal.next_step.dismissed"
    if row.status == AgentProposalStatus.EXPIRED:
        return "agents.proposal.next_step.expired"
    return "agents.proposal.next_step.superseded"


def proposal_can_create_ticket(row: AgentProposal) -> bool:
    return row.status == AgentProposalStatus.OPEN and proposal_execution_mode(row) == "approval_ticket_required"


def ticket_lifecycle_code(row: ApprovalTicket) -> str:
    return f"agents.ticket.lifecycle.{row.status.value}"


def ticket_next_step_code(row: ApprovalTicket) -> str:
    if row.status == ApprovalTicketStatus.OPEN:
        return "agents.ticket.next_step.confirm_or_cancel"
    if row.status == ApprovalTicketStatus.EXECUTED:
        return "agents.ticket.next_step.completed"
    if row.status == ApprovalTicketStatus.CANCELED:
        return "agents.ticket.next_step.canceled"
    if row.status == ApprovalTicketStatus.EXPIRED:
        return "agents.ticket.next_step.expired"
    return "agents.ticket.next_step.investigate_failure"


def ticket_can_confirm(row: ApprovalTicket) -> bool:
    return row.status == ApprovalTicketStatus.OPEN


def ticket_can_cancel(row: ApprovalTicket) -> bool:
    return row.status == ApprovalTicketStatus.OPEN


def ticket_confirm_summary_code(row: ApprovalTicket) -> str:
    return f"agents.ticket.confirm.{row.action_type}.summary"


def ticket_cancel_summary_code(row: ApprovalTicket) -> str:
    return f"agents.ticket.cancel.{row.action_type}.summary"


def ticket_transition_message_code(row: ApprovalTicket) -> str:
    if row.status == ApprovalTicketStatus.OPEN:
        return f"agents.ticket.transition.{row.action_type}.waiting_confirm"
    if row.status == ApprovalTicketStatus.EXECUTED:
        return f"agents.ticket.transition.{row.action_type}.executed"
    if row.status == ApprovalTicketStatus.CANCELED:
        return f"agents.ticket.transition.{row.action_type}.canceled"
    if row.status == ApprovalTicketStatus.EXPIRED:
        return f"agents.ticket.transition.{row.action_type}.expired"
    return f"agents.ticket.transition.{row.action_type}.failed"


def ticket_social_safe_cta_code(row: ApprovalTicket) -> str | None:
    if row.status == ApprovalTicketStatus.OPEN and str(row.risk_level or "") == "low":
        return "agents.ticket.cta.confirm"
    return None


__all__ = [
    "proposal_can_create_ticket",
    "proposal_execution_mode",
    "proposal_execution_mode_code",
    "proposal_lifecycle_code",
    "proposal_next_step_code",
    "ticket_can_cancel",
    "ticket_can_confirm",
    "ticket_cancel_summary_code",
    "ticket_confirm_summary_code",
    "ticket_lifecycle_code",
    "ticket_next_step_code",
    "ticket_social_safe_cta_code",
    "ticket_transition_message_code",
]
