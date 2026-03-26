from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.modules.agents.language_context import (
    AgentLanguageContext,
    collect_agent_input_texts,
    resolve_agent_language_context,
)
from app.modules.common.language import normalize_language_code
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
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
    payload = build_workspace_agent_context(
        db=db,
        user_id=user_id,
        language_code=language_context.effective_language_code,
    )
    return _attach_language_metadata(payload, language_context=language_context)


def get_change_context(db: Session, *, user_id: int, change_id: int, language_code: str | None = None) -> dict:
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
    payload = build_change_agent_context(
        db=db,
        user_id=user_id,
        change_id=change_id,
        language_code=language_context.effective_language_code,
    )
    return _attach_language_metadata(payload, language_context=language_context)


def get_source_context(db: Session, *, user_id: int, source_id: int, language_code: str | None = None) -> dict:
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
    payload = build_source_agent_context(
        db=db,
        user_id=user_id,
        source_id=source_id,
        language_code=language_context.effective_language_code,
    )
    return _attach_language_metadata(payload, language_context=language_context)


def get_family_context(db: Session, *, user_id: int, family_id: int, language_code: str | None = None) -> dict:
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
    payload = build_family_agent_context(
        db=db,
        user_id=user_id,
        family_id=family_id,
        language_code=language_context.effective_language_code,
    )
    return _attach_language_metadata(payload, language_context=language_context)


def get_recent_activity(db: Session, *, user_id: int, limit: int = 20, language_code: str | None = None) -> dict:
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
    payload = build_recent_agent_activity(
        db=db,
        user_id=user_id,
        limit=limit,
        language_code=language_context.effective_language_code,
    )
    return _attach_language_metadata(payload, language_context=language_context)


def get_proposal(db: Session, *, user_id: int, proposal_id: int, language_code: str | None = None) -> dict | None:
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
    proposal = get_agent_proposal(db=db, user_id=user_id, proposal_id=proposal_id)
    if proposal is None:
        return None
    return serialize_agent_proposal(
        proposal,
        language_code=language_context.effective_language_code,
        language_resolution_source=language_context.resolution_source,
    )


def list_proposals(
    db: Session,
    *,
    user_id: int,
    status: str = "all",
    limit: int = 20,
    language_code: str | None = None,
) -> list[dict]:
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
    return [
        _serialize_agent_proposal_with_language(
            row,
            language_code=language_context.effective_language_code,
            language_resolution_source=language_context.resolution_source,
        )
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
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
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
    return _serialize_agent_proposal_with_language(
        proposal,
        language_code=language_context.effective_language_code,
        language_resolution_source=language_context.resolution_source,
    )


def create_change_edit_commit_proposal(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    patch: dict,
    origin: AgentGatewayOrigin | None = None,
    language_code: str | None = None,
) -> dict:
    language_context = _resolve_language_context(
        db,
        user_id=user_id,
        language_code=language_code,
        input_texts=collect_agent_input_texts(patch),
    )
    resolved_origin = origin or AgentGatewayOrigin()
    proposal = create_change_edit_commit_proposal_with_origin(
        db=db,
        user_id=user_id,
        change_id=change_id,
        patch=patch,
        origin_kind=resolved_origin.kind,
        origin_label=resolved_origin.label,
        origin_request_id=resolved_origin.request_id,
        language_code=language_code,
    )
    return _serialize_agent_proposal_with_language(
        proposal,
        language_code=language_context.effective_language_code,
        language_resolution_source=language_context.resolution_source,
    )


def create_source_recovery_proposal(
    db: Session,
    *,
    user_id: int,
    source_id: int,
    origin: AgentGatewayOrigin | None = None,
    language_code: str | None = None,
) -> dict:
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
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
    return _serialize_agent_proposal_with_language(
        proposal,
        language_code=language_context.effective_language_code,
        language_resolution_source=language_context.resolution_source,
    )


def create_family_relink_preview_proposal(
    db: Session,
    *,
    user_id: int,
    raw_type_id: int,
    family_id: int,
    origin: AgentGatewayOrigin | None = None,
    language_code: str | None = None,
) -> dict:
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
    resolved_origin = origin or AgentGatewayOrigin()
    proposal = create_family_relink_preview_proposal_with_origin(
        db=db,
        user_id=user_id,
        raw_type_id=raw_type_id,
        family_id=family_id,
        origin_kind=resolved_origin.kind,
        origin_label=resolved_origin.label,
        origin_request_id=resolved_origin.request_id,
        language_code=language_code,
    )
    return _serialize_agent_proposal_with_language(
        proposal,
        language_code=language_context.effective_language_code,
        language_resolution_source=language_context.resolution_source,
    )


def create_family_relink_commit_proposal(
    db: Session,
    *,
    user_id: int,
    raw_type_id: int,
    family_id: int,
    origin: AgentGatewayOrigin | None = None,
    language_code: str | None = None,
) -> dict:
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
    resolved_origin = origin or AgentGatewayOrigin()
    proposal = create_family_relink_commit_proposal_with_origin(
        db=db,
        user_id=user_id,
        raw_type_id=raw_type_id,
        family_id=family_id,
        origin_kind=resolved_origin.kind,
        origin_label=resolved_origin.label,
        origin_request_id=resolved_origin.request_id,
        language_code=language_code,
    )
    return _serialize_agent_proposal_with_language(
        proposal,
        language_code=language_context.effective_language_code,
        language_resolution_source=language_context.resolution_source,
    )


def create_label_learning_commit_proposal(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    family_id: int,
    origin: AgentGatewayOrigin | None = None,
    language_code: str | None = None,
) -> dict:
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
    resolved_origin = origin or AgentGatewayOrigin()
    proposal = create_label_learning_commit_proposal_with_origin(
        db=db,
        user_id=user_id,
        change_id=change_id,
        family_id=family_id,
        origin_kind=resolved_origin.kind,
        origin_label=resolved_origin.label,
        origin_request_id=resolved_origin.request_id,
        language_code=language_code,
    )
    return _serialize_agent_proposal_with_language(
        proposal,
        language_code=language_context.effective_language_code,
        language_resolution_source=language_context.resolution_source,
    )


def create_approval_ticket_for_proposal(
    db: Session,
    *,
    user_id: int,
    proposal_id: int,
    channel: str,
    origin: AgentGatewayOrigin | None = None,
    language_code: str | None = None,
) -> dict:
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
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
    return _serialize_approval_ticket_with_language(
        ticket,
        language_code=language_context.effective_language_code,
        language_resolution_source=language_context.resolution_source,
    )


def get_approval_ticket_for_user(
    db: Session,
    *,
    user_id: int,
    ticket_id: str,
    language_code: str | None = None,
) -> dict | None:
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
    ticket = get_approval_ticket(db=db, user_id=user_id, ticket_id=ticket_id)
    if ticket is None:
        return None
    return _serialize_approval_ticket_with_language(
        ticket,
        language_code=language_context.effective_language_code,
        language_resolution_source=language_context.resolution_source,
    )


def list_approval_tickets_for_user(
    db: Session,
    *,
    user_id: int,
    status: str = "all",
    limit: int = 20,
    language_code: str | None = None,
) -> list[dict]:
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
    return [
        _serialize_approval_ticket_with_language(
            row,
            language_code=language_context.effective_language_code,
            language_resolution_source=language_context.resolution_source,
        )
        for row in list_approval_tickets(db=db, user_id=user_id, status=status, limit=limit)
    ]


def confirm_approval_ticket_for_user(
    db: Session,
    *,
    user_id: int,
    ticket_id: str,
    origin: AgentGatewayOrigin | None = None,
    language_code: str | None = None,
) -> dict:
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
    resolved_origin = origin or AgentGatewayOrigin()
    ticket, _idempotent = confirm_approval_ticket(
        db=db,
        user_id=user_id,
        ticket_id=ticket_id,
        transition_kind=resolved_origin.kind,
        transition_label=resolved_origin.label,
    )
    return _serialize_approval_ticket_with_language(
        ticket,
        language_code=language_context.effective_language_code,
        language_resolution_source=language_context.resolution_source,
    )


def cancel_approval_ticket_for_user(
    db: Session,
    *,
    user_id: int,
    ticket_id: str,
    origin: AgentGatewayOrigin | None = None,
    language_code: str | None = None,
) -> dict:
    language_context = _resolve_language_context(db, user_id=user_id, language_code=language_code)
    resolved_origin = origin or AgentGatewayOrigin()
    ticket, _idempotent = cancel_approval_ticket(
        db=db,
        user_id=user_id,
        ticket_id=ticket_id,
        transition_kind=resolved_origin.kind,
        transition_label=resolved_origin.label,
    )
    return _serialize_approval_ticket_with_language(
        ticket,
        language_code=language_context.effective_language_code,
        language_resolution_source=language_context.resolution_source,
    )


def _resolve_language_context(
    db: Session,
    *,
    user_id: int,
    language_code: str | None,
    input_texts: list[str] | None = None,
) -> AgentLanguageContext:
    if not hasattr(db, "scalar"):
        if isinstance(language_code, str) and language_code.strip():
            normalized = normalize_language_code(language_code)
            return AgentLanguageContext(
                effective_language_code=normalized,
                input_language_code=None,
                system_language_code=normalized,
                resolution_source="explicit",
            )
        return AgentLanguageContext(
            effective_language_code="en",
            input_language_code=None,
            system_language_code="en",
            resolution_source="default",
        )
    return resolve_agent_language_context(
        db,
        user_id=user_id,
        explicit_language_code=language_code,
        input_texts=input_texts or [],
    )


def _serialize_agent_proposal_with_language(row, *, language_code: str, language_resolution_source: str):
    try:
        return serialize_agent_proposal(
            row,
            language_code=language_code,
            language_resolution_source=language_resolution_source,
        )
    except TypeError:
        return serialize_agent_proposal(row, language_code=language_code)


def _serialize_approval_ticket_with_language(row, *, language_code: str, language_resolution_source: str):
    try:
        return serialize_approval_ticket(
            row,
            language_code=language_code,
            language_resolution_source=language_resolution_source,
        )
    except TypeError:
        return serialize_approval_ticket(row)


def _attach_language_metadata(payload: dict, *, language_context: AgentLanguageContext) -> dict:
    output = dict(payload)
    output["language_code"] = language_context.effective_language_code
    output["language_resolution_source"] = language_context.resolution_source
    return output


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
