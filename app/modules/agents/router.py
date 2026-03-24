from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.session import get_db
from app.modules.agents.schemas import (
    AgentChangeDecisionProposalRequest,
    AgentChangeContextResponse,
    AgentFamilyRelinkPreviewProposalRequest,
    AgentFamilyContextResponse,
    AgentProposalResponse,
    AgentRecentActivityResponse,
    AgentSourceRecoveryProposalRequest,
    AgentSourceContextResponse,
    AgentWorkspaceContextResponse,
    ApprovalTicketCancelRequest,
    ApprovalTicketConfirmRequest,
    ApprovalTicketCreateRequest,
    ApprovalTicketResponse,
    serialize_approval_ticket,
    serialize_agent_proposal,
)
from app.modules.agents.activity_service import (
    PROPOSAL_STATUS_VALUES,
    TICKET_STATUS_VALUES,
    build_recent_agent_activity,
    list_agent_proposals,
    list_approval_tickets,
)
from app.modules.agents.approval_service import (
    ApprovalTicketError,
    cancel_approval_ticket,
    confirm_approval_ticket,
    create_approval_ticket,
    get_approval_ticket,
)
from app.modules.agents.service import (
    AgentContextNotFoundError,
    build_change_agent_context,
    build_family_agent_context,
    build_source_agent_context,
    build_workspace_agent_context,
)
from app.modules.agents.proposal_service import (
    AgentProposalInvalidStateError,
    create_change_decision_proposal,
    create_family_relink_preview_proposal,
    create_source_recovery_proposal,
    get_agent_proposal,
)
from app.modules.auth.deps import get_onboarded_authenticated_user_or_409 as get_onboarded_user_or_409

router = APIRouter(prefix="/agent", tags=["agents"], dependencies=[Depends(require_public_api_key)])


@router.get("/context/workspace", response_model=AgentWorkspaceContextResponse)
def get_agent_workspace_context(
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> AgentWorkspaceContextResponse:
    return AgentWorkspaceContextResponse.model_validate(
        build_workspace_agent_context(db=db, user_id=user.id)
    )


@router.get("/context/changes/{change_id}", response_model=AgentChangeContextResponse)
def get_agent_change_context(
    change_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> AgentChangeContextResponse:
    try:
        payload = build_change_agent_context(db=db, user_id=user.id, change_id=change_id)
    except AgentContextNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.detail) from exc
    return AgentChangeContextResponse.model_validate(payload)


@router.get("/context/sources/{source_id}", response_model=AgentSourceContextResponse)
def get_agent_source_context(
    source_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> AgentSourceContextResponse:
    try:
        payload = build_source_agent_context(db=db, user_id=user.id, source_id=source_id)
    except AgentContextNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.detail) from exc
    return AgentSourceContextResponse.model_validate(payload)


@router.get("/context/families/{family_id}", response_model=AgentFamilyContextResponse)
def get_agent_family_context(
    family_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> AgentFamilyContextResponse:
    try:
        payload = build_family_agent_context(db=db, user_id=user.id, family_id=family_id)
    except AgentContextNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.detail) from exc
    return AgentFamilyContextResponse.model_validate(payload)


@router.post("/proposals/change-decision", response_model=AgentProposalResponse, status_code=status.HTTP_201_CREATED)
def post_agent_change_decision_proposal(
    payload: AgentChangeDecisionProposalRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> AgentProposalResponse:
    try:
        proposal = create_change_decision_proposal(db=db, user_id=user.id, change_id=payload.change_id)
    except AgentContextNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.detail) from exc
    except AgentProposalInvalidStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail) from exc
    return AgentProposalResponse.model_validate(serialize_agent_proposal(proposal))


@router.post("/proposals/source-recovery", response_model=AgentProposalResponse, status_code=status.HTTP_201_CREATED)
def post_agent_source_recovery_proposal(
    payload: AgentSourceRecoveryProposalRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> AgentProposalResponse:
    try:
        proposal = create_source_recovery_proposal(db=db, user_id=user.id, source_id=payload.source_id)
    except AgentContextNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.detail) from exc
    return AgentProposalResponse.model_validate(serialize_agent_proposal(proposal))


@router.post("/proposals/family-relink-preview", response_model=AgentProposalResponse, status_code=status.HTTP_201_CREATED)
def post_agent_family_relink_preview_proposal(
    payload: AgentFamilyRelinkPreviewProposalRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> AgentProposalResponse:
    try:
        proposal = create_family_relink_preview_proposal(
            db=db,
            user_id=user.id,
            raw_type_id=payload.raw_type_id,
            family_id=payload.family_id,
        )
    except AgentContextNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.detail) from exc
    except AgentProposalInvalidStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail) from exc
    return AgentProposalResponse.model_validate(serialize_agent_proposal(proposal))


@router.get("/proposals", response_model=list[AgentProposalResponse])
def get_agent_proposals_route(
    status_filter: str = "all",
    limit: int = 20,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> list[AgentProposalResponse]:
    normalized_status = status_filter.strip().lower() if isinstance(status_filter, str) else "all"
    if normalized_status not in PROPOSAL_STATUS_VALUES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "agents.proposals.invalid_status_filter",
                "message": "proposal status must be one of: open, accepted, rejected, expired, superseded, all",
                "message_code": "agents.proposals.invalid_status_filter",
                "message_params": {},
            },
        )
    rows = list_agent_proposals(db=db, user_id=user.id, status=normalized_status, limit=max(1, min(int(limit), 100)))
    return [AgentProposalResponse.model_validate(serialize_agent_proposal(row)) for row in rows]


@router.get("/proposals/{proposal_id}", response_model=AgentProposalResponse)
def get_agent_proposal_route(
    proposal_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> AgentProposalResponse:
    proposal = get_agent_proposal(db=db, user_id=user.id, proposal_id=proposal_id)
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "agents.proposals.not_found",
                "message": "Agent proposal not found",
                "message_code": "agents.proposals.not_found",
                "message_params": {},
            },
    )
    return AgentProposalResponse.model_validate(serialize_agent_proposal(proposal))


@router.get("/approval-tickets", response_model=list[ApprovalTicketResponse])
def get_approval_tickets_route(
    status_filter: str = "all",
    limit: int = 20,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> list[ApprovalTicketResponse]:
    normalized_status = status_filter.strip().lower() if isinstance(status_filter, str) else "all"
    if normalized_status not in TICKET_STATUS_VALUES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "agents.approval.invalid_status_filter",
                "message": "approval ticket status must be one of: open, executed, canceled, expired, failed, all",
                "message_code": "agents.approval.invalid_status_filter",
                "message_params": {},
            },
        )
    rows = list_approval_tickets(db=db, user_id=user.id, status=normalized_status, limit=max(1, min(int(limit), 100)))
    return [ApprovalTicketResponse.model_validate(serialize_approval_ticket(row)) for row in rows]


@router.post("/approval-tickets", response_model=ApprovalTicketResponse, status_code=status.HTTP_201_CREATED)
def post_approval_ticket(
    payload: ApprovalTicketCreateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ApprovalTicketResponse:
    try:
        ticket = create_approval_ticket(db=db, user_id=user.id, proposal_id=payload.proposal_id, channel=payload.channel)
    except ApprovalTicketError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return ApprovalTicketResponse.model_validate(serialize_approval_ticket(ticket))


@router.get("/activity/recent", response_model=AgentRecentActivityResponse)
def get_recent_agent_activity_route(
    limit: int = 20,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> AgentRecentActivityResponse:
    payload = build_recent_agent_activity(db=db, user_id=user.id, limit=max(1, min(int(limit), 100)))
    return AgentRecentActivityResponse.model_validate(payload)


@router.get("/approval-tickets/{ticket_id}", response_model=ApprovalTicketResponse)
def get_approval_ticket_route(
    ticket_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ApprovalTicketResponse:
    ticket = get_approval_ticket(db=db, user_id=user.id, ticket_id=ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "agents.approval.ticket_not_found",
                "message": "Approval ticket not found",
                "message_code": "agents.approval.ticket_not_found",
                "message_params": {},
            },
        )
    return ApprovalTicketResponse.model_validate(serialize_approval_ticket(ticket))


@router.post("/approval-tickets/{ticket_id}/confirm", response_model=ApprovalTicketResponse)
def post_approval_ticket_confirm(
    ticket_id: str,
    payload: ApprovalTicketConfirmRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ApprovalTicketResponse:
    del payload
    try:
        ticket, _idempotent = confirm_approval_ticket(db=db, user_id=user.id, ticket_id=ticket_id)
    except ApprovalTicketError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return ApprovalTicketResponse.model_validate(serialize_approval_ticket(ticket))


@router.post("/approval-tickets/{ticket_id}/cancel", response_model=ApprovalTicketResponse)
def post_approval_ticket_cancel(
    ticket_id: str,
    payload: ApprovalTicketCancelRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ApprovalTicketResponse:
    del payload
    try:
        ticket, _idempotent = cancel_approval_ticket(db=db, user_id=user.id, ticket_id=ticket_id)
    except ApprovalTicketError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return ApprovalTicketResponse.model_validate(serialize_approval_ticket(ticket))


__all__ = ["router"]
