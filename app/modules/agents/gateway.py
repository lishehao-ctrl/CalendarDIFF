from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.modules.agents.activity_service import (
    build_recent_agent_activity,
    list_agent_proposals,
    list_approval_tickets,
)
from app.modules.agents.approval_service import (
    cancel_approval_ticket,
    confirm_approval_ticket,
    create_approval_ticket,
    get_approval_ticket,
)
from app.modules.agents.proposal_service import (
    create_change_decision_proposal_with_origin,
    create_change_edit_commit_proposal_with_origin,
    create_family_relink_commit_proposal_with_origin,
    create_family_relink_preview_proposal_with_origin,
    create_label_learning_commit_proposal_with_origin,
    create_source_recovery_proposal_with_origin,
    get_agent_proposal,
)
from app.modules.agents.schemas import serialize_approval_ticket, serialize_agent_proposal
from app.modules.agents.service import (
    build_change_agent_context,
    build_family_agent_context,
    build_source_agent_context,
    build_workspace_agent_context,
)


@dataclass(frozen=True)
class AgentGatewayOrigin:
    kind: str = "web"
    label: str = "embedded_agent"
    request_id: str | None = None


def get_workspace_context(db: Session, *, user_id: int, language_code: str | None = None) -> dict:
    return build_workspace_agent_context(db=db, user_id=user_id, language_code=language_code)


def get_change_context(db: Session, *, user_id: int, change_id: int, language_code: str | None = None) -> dict:
    return build_change_agent_context(db=db, user_id=user_id, change_id=change_id, language_code=language_code)


def get_source_context(db: Session, *, user_id: int, source_id: int, language_code: str | None = None) -> dict:
    return build_source_agent_context(db=db, user_id=user_id, source_id=source_id, language_code=language_code)


def get_family_context(db: Session, *, user_id: int, family_id: int) -> dict:
    return build_family_agent_context(db=db, user_id=user_id, family_id=family_id)


def get_recent_activity(db: Session, *, user_id: int, limit: int = 20) -> dict:
    return build_recent_agent_activity(db=db, user_id=user_id, limit=limit)


def get_proposal(db: Session, *, user_id: int, proposal_id: int, language_code: str | None = None) -> dict | None:
    proposal = get_agent_proposal(db=db, user_id=user_id, proposal_id=proposal_id)
    if proposal is None:
        return None
    return serialize_agent_proposal(proposal, language_code=language_code)


def list_proposals(
    db: Session,
    *,
    user_id: int,
    status: str = "all",
    limit: int = 20,
    language_code: str | None = None,
) -> list[dict]:
    return [
        serialize_agent_proposal(row, language_code=language_code)
        for row in list_agent_proposals(db=db, user_id=user_id, status=status, limit=limit)
    ]


def create_change_decision_proposal(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    origin: AgentGatewayOrigin | None = None,
    language_code: str | None = None,
) -> dict:
    resolved_origin = origin or AgentGatewayOrigin()
    proposal = create_change_decision_proposal_with_origin(
        db=db,
        user_id=user_id,
        change_id=change_id,
        origin_kind=resolved_origin.kind,
        origin_label=resolved_origin.label,
        origin_request_id=resolved_origin.request_id,
        language_code=language_code,
    )
    return serialize_agent_proposal(proposal, language_code=language_code)


def create_change_edit_commit_proposal(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    patch: dict,
    origin: AgentGatewayOrigin | None = None,
) -> dict:
    resolved_origin = origin or AgentGatewayOrigin()
    proposal = create_change_edit_commit_proposal_with_origin(
        db=db,
        user_id=user_id,
        change_id=change_id,
        patch=patch,
        origin_kind=resolved_origin.kind,
        origin_label=resolved_origin.label,
        origin_request_id=resolved_origin.request_id,
    )
    return serialize_agent_proposal(proposal)


def create_source_recovery_proposal(
    db: Session,
    *,
    user_id: int,
    source_id: int,
    origin: AgentGatewayOrigin | None = None,
    language_code: str | None = None,
) -> dict:
    resolved_origin = origin or AgentGatewayOrigin()
    proposal = create_source_recovery_proposal_with_origin(
        db=db,
        user_id=user_id,
        source_id=source_id,
        origin_kind=resolved_origin.kind,
        origin_label=resolved_origin.label,
        origin_request_id=resolved_origin.request_id,
        language_code=language_code,
    )
    return serialize_agent_proposal(proposal, language_code=language_code)


def create_family_relink_preview_proposal(
    db: Session,
    *,
    user_id: int,
    raw_type_id: int,
    family_id: int,
    origin: AgentGatewayOrigin | None = None,
) -> dict:
    resolved_origin = origin or AgentGatewayOrigin()
    proposal = create_family_relink_preview_proposal_with_origin(
        db=db,
        user_id=user_id,
        raw_type_id=raw_type_id,
        family_id=family_id,
        origin_kind=resolved_origin.kind,
        origin_label=resolved_origin.label,
        origin_request_id=resolved_origin.request_id,
    )
    return serialize_agent_proposal(proposal)


def create_family_relink_commit_proposal(
    db: Session,
    *,
    user_id: int,
    raw_type_id: int,
    family_id: int,
    origin: AgentGatewayOrigin | None = None,
) -> dict:
    resolved_origin = origin or AgentGatewayOrigin()
    proposal = create_family_relink_commit_proposal_with_origin(
        db=db,
        user_id=user_id,
        raw_type_id=raw_type_id,
        family_id=family_id,
        origin_kind=resolved_origin.kind,
        origin_label=resolved_origin.label,
        origin_request_id=resolved_origin.request_id,
    )
    return serialize_agent_proposal(proposal)


def create_label_learning_commit_proposal(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    family_id: int,
    origin: AgentGatewayOrigin | None = None,
) -> dict:
    resolved_origin = origin or AgentGatewayOrigin()
    proposal = create_label_learning_commit_proposal_with_origin(
        db=db,
        user_id=user_id,
        change_id=change_id,
        family_id=family_id,
        origin_kind=resolved_origin.kind,
        origin_label=resolved_origin.label,
        origin_request_id=resolved_origin.request_id,
    )
    return serialize_agent_proposal(proposal)


def create_approval_ticket_for_proposal(
    db: Session,
    *,
    user_id: int,
    proposal_id: int,
    channel: str,
    origin: AgentGatewayOrigin | None = None,
) -> dict:
    resolved_origin = origin or AgentGatewayOrigin()
    ticket = create_approval_ticket(
        db=db,
        user_id=user_id,
        proposal_id=proposal_id,
        channel=channel,
        origin_kind=resolved_origin.kind,
        origin_label=resolved_origin.label,
        origin_request_id=resolved_origin.request_id,
    )
    return serialize_approval_ticket(ticket)


def get_approval_ticket_for_user(db: Session, *, user_id: int, ticket_id: str) -> dict | None:
    ticket = get_approval_ticket(db=db, user_id=user_id, ticket_id=ticket_id)
    if ticket is None:
        return None
    return serialize_approval_ticket(ticket)


def list_approval_tickets_for_user(
    db: Session,
    *,
    user_id: int,
    status: str = "all",
    limit: int = 20,
) -> list[dict]:
    return [
        serialize_approval_ticket(row)
        for row in list_approval_tickets(db=db, user_id=user_id, status=status, limit=limit)
    ]


def confirm_approval_ticket_for_user(
    db: Session,
    *,
    user_id: int,
    ticket_id: str,
    origin: AgentGatewayOrigin | None = None,
) -> dict:
    resolved_origin = origin or AgentGatewayOrigin()
    ticket, _idempotent = confirm_approval_ticket(
        db=db,
        user_id=user_id,
        ticket_id=ticket_id,
        transition_kind=resolved_origin.kind,
        transition_label=resolved_origin.label,
    )
    return serialize_approval_ticket(ticket)


def cancel_approval_ticket_for_user(
    db: Session,
    *,
    user_id: int,
    ticket_id: str,
    origin: AgentGatewayOrigin | None = None,
) -> dict:
    resolved_origin = origin or AgentGatewayOrigin()
    ticket, _idempotent = cancel_approval_ticket(
        db=db,
        user_id=user_id,
        ticket_id=ticket_id,
        transition_kind=resolved_origin.kind,
        transition_label=resolved_origin.label,
    )
    return serialize_approval_ticket(ticket)


__all__ = [
    "AgentGatewayOrigin",
    "cancel_approval_ticket_for_user",
    "confirm_approval_ticket_for_user",
    "create_approval_ticket_for_proposal",
    "create_change_decision_proposal",
    "create_change_edit_commit_proposal",
    "create_family_relink_commit_proposal",
    "create_family_relink_preview_proposal",
    "create_label_learning_commit_proposal",
    "create_source_recovery_proposal",
    "get_approval_ticket_for_user",
    "get_change_context",
    "get_family_context",
    "get_proposal",
    "get_recent_activity",
    "get_source_context",
    "get_workspace_context",
    "list_approval_tickets_for_user",
    "list_proposals",
]
