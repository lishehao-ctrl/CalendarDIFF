from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.agents import ApprovalTicket, AgentProposal
from app.modules.agents.lifecycle import (
    proposal_can_create_ticket,
    proposal_execution_mode,
    proposal_execution_mode_code,
    proposal_lifecycle_code,
    proposal_next_step_code,
    ticket_can_cancel,
    ticket_can_confirm,
    ticket_cancel_summary_code,
    ticket_confirm_summary_code,
    ticket_lifecycle_code,
    ticket_next_step_code,
    ticket_social_safe_cta_code,
    ticket_transition_message_code,
)


PROPOSAL_STATUS_VALUES = {"open", "accepted", "rejected", "expired", "superseded", "all"}
TICKET_STATUS_VALUES = {"open", "executed", "canceled", "expired", "failed", "all"}


def list_agent_proposals(
    db: Session,
    *,
    user_id: int,
    status: str = "all",
    limit: int = 20,
) -> list[AgentProposal]:
    normalized_status = status.strip().lower() if isinstance(status, str) else "all"
    stmt = select(AgentProposal).where(AgentProposal.user_id == user_id)
    if normalized_status != "all":
        stmt = stmt.where(AgentProposal.status == normalized_status)
    stmt = stmt.order_by(AgentProposal.updated_at.desc(), AgentProposal.created_at.desc(), AgentProposal.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def list_approval_tickets(
    db: Session,
    *,
    user_id: int,
    status: str = "all",
    limit: int = 20,
) -> list[ApprovalTicket]:
    normalized_status = status.strip().lower() if isinstance(status, str) else "all"
    stmt = select(ApprovalTicket).where(ApprovalTicket.user_id == user_id)
    if normalized_status != "all":
        stmt = stmt.where(ApprovalTicket.status == normalized_status)
    stmt = stmt.order_by(ApprovalTicket.updated_at.desc(), ApprovalTicket.created_at.desc(), ApprovalTicket.ticket_id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def build_recent_agent_activity(
    db: Session,
    *,
    user_id: int,
    limit: int = 20,
) -> dict:
    proposals = list_agent_proposals(db, user_id=user_id, status="all", limit=limit)
    tickets = list_approval_tickets(db, user_id=user_id, status="all", limit=limit)

    items = [_serialize_proposal_activity(row) for row in proposals] + [_serialize_ticket_activity(row) for row in tickets]
    items.sort(key=lambda row: (_occurred_at_sort_key(row.get("occurred_at")), row.get("activity_id") or ""), reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc),
        "items": items[:limit],
    }


def _serialize_proposal_activity(row: AgentProposal) -> dict:
    return {
        "item_kind": "proposal",
        "activity_id": f"proposal:{row.id}",
        "occurred_at": row.updated_at or row.created_at,
        "owner_user_id": row.user_id,
        "proposal_id": row.id,
        "ticket_id": None,
        "status": row.status.value,
        "lifecycle_code": proposal_lifecycle_code(row),
        "next_step_code": proposal_next_step_code(row),
        "risk_level": row.risk_level,
        "target_kind": row.target_kind,
        "target_id": row.target_id,
        "summary": row.summary,
        "summary_code": row.summary_code,
        "detail": row.reason,
        "detail_code": row.reason_code,
        "origin_kind": row.origin_kind,
        "origin_label": row.origin_label,
        "origin_request_id": row.origin_request_id,
        "channel": None,
        "execution_mode": proposal_execution_mode(row),
        "execution_mode_code": proposal_execution_mode_code(row),
        "confirm_summary_code": None,
        "cancel_summary_code": None,
        "transition_message_code": None,
        "social_safe_cta_code": None,
        "can_create_ticket": proposal_can_create_ticket(row),
        "can_confirm": False,
        "can_cancel": False,
        "last_transition_kind": None,
        "last_transition_label": None,
        "suggested_action": row.suggested_action,
        "action_type": None,
    }


def _serialize_ticket_activity(row: ApprovalTicket) -> dict:
    return {
        "item_kind": "ticket",
        "activity_id": f"ticket:{row.ticket_id}",
        "occurred_at": row.updated_at or row.created_at,
        "owner_user_id": row.user_id,
        "proposal_id": row.proposal_id,
        "ticket_id": row.ticket_id,
        "status": row.status.value,
        "lifecycle_code": ticket_lifecycle_code(row),
        "next_step_code": ticket_next_step_code(row),
        "risk_level": row.risk_level,
        "target_kind": row.target_kind,
        "target_id": row.target_id,
        "summary": _ticket_summary(row),
        "summary_code": f"agents.activity.ticket.{row.status.value}",
        "detail": _ticket_detail(row),
        "detail_code": f"agents.activity.ticket.{row.action_type}.{row.status.value}",
        "origin_kind": row.origin_kind,
        "origin_label": row.origin_label,
        "origin_request_id": row.origin_request_id,
        "channel": row.channel,
        "execution_mode": None,
        "execution_mode_code": None,
        "confirm_summary_code": ticket_confirm_summary_code(row),
        "cancel_summary_code": ticket_cancel_summary_code(row),
        "transition_message_code": ticket_transition_message_code(row),
        "social_safe_cta_code": ticket_social_safe_cta_code(row),
        "can_create_ticket": False,
        "can_confirm": ticket_can_confirm(row),
        "can_cancel": ticket_can_cancel(row),
        "last_transition_kind": row.last_transition_kind,
        "last_transition_label": row.last_transition_label,
        "suggested_action": None,
        "action_type": row.action_type,
    }


def _ticket_summary(row: ApprovalTicket) -> str:
    status_label = row.status.value.replace("_", " ")
    action_label = row.action_type.replace("_", " ")
    return f"{action_label.title()} ticket {status_label}."


def _ticket_detail(row: ApprovalTicket) -> str:
    if row.status.value == "executed":
        return "The approval ticket executed through the bounded agent gateway."
    if row.status.value == "canceled":
        return "The approval ticket was canceled before execution."
    if row.status.value == "failed":
        return "The approval ticket attempted execution but failed."
    if row.status.value == "expired":
        return "The approval ticket expired before confirmation."
    return "The approval ticket is still waiting for confirmation."


def _occurred_at_sort_key(value: object) -> float:
    if isinstance(value, datetime):
        timestamp = value.timestamp()
        return float(timestamp)
    return 0.0


__all__ = [
    "PROPOSAL_STATUS_VALUES",
    "TICKET_STATUS_VALUES",
    "build_recent_agent_activity",
    "list_agent_proposals",
    "list_approval_tickets",
]
