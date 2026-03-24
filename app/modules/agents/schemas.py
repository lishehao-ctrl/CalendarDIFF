from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.changes.schemas import ChangeItemResponse, ChangesWorkbenchSummaryResponse
from app.modules.families.schemas import (
    CourseRawTypeResponse,
    CourseWorkItemFamilyResponse,
    RawTypeSuggestionItemResponse,
)
from app.modules.sources.schemas import InputSourceResponse, SourceObservabilityResponse, SyncRequestStatusResponse

AgentRiskLevelLiteral = Literal["low", "medium", "high"]
AgentConditionSeverityLiteral = Literal["info", "warning", "blocking"]
AgentProposalTypeLiteral = Literal["change_decision", "source_recovery", "family_relink_preview"]
AgentProposalStatusLiteral = Literal["open", "accepted", "rejected", "expired", "superseded"]
ApprovalTicketStatusLiteral = Literal["open", "executed", "canceled", "expired", "failed"]
AgentActivityKindLiteral = Literal["proposal", "ticket"]
AgentExecutionModeLiteral = Literal["approval_ticket_required", "web_only"]


class AgentBlockingConditionResponse(BaseModel):
    code: str
    message: str
    severity: AgentConditionSeverityLiteral


class AgentRecommendedActionResponse(BaseModel):
    lane: Literal["sources", "initial_review", "changes", "families", "manual"]
    label: str
    reason: str
    reason_code: str
    reason_params: dict = Field(default_factory=dict)
    risk_level: AgentRiskLevelLiteral
    recommended_tool: str


class AgentWorkspaceContextResponse(BaseModel):
    generated_at: datetime
    summary: ChangesWorkbenchSummaryResponse
    top_pending_changes: list[ChangeItemResponse]
    recommended_next_action: AgentRecommendedActionResponse
    blocking_conditions: list[AgentBlockingConditionResponse] = Field(default_factory=list)
    available_next_tools: list[str] = Field(default_factory=list)


class AgentChangeContextResponse(BaseModel):
    generated_at: datetime
    change: ChangeItemResponse
    recommended_next_action: AgentRecommendedActionResponse
    blocking_conditions: list[AgentBlockingConditionResponse] = Field(default_factory=list)
    available_next_tools: list[str] = Field(default_factory=list)


class AgentSourceContextResponse(BaseModel):
    generated_at: datetime
    source: InputSourceResponse
    observability: SourceObservabilityResponse
    active_sync_request: SyncRequestStatusResponse | None = None
    recommended_next_action: AgentRecommendedActionResponse
    blocking_conditions: list[AgentBlockingConditionResponse] = Field(default_factory=list)
    available_next_tools: list[str] = Field(default_factory=list)


class AgentFamilyContextResponse(BaseModel):
    generated_at: datetime
    family: CourseWorkItemFamilyResponse
    raw_types: list[CourseRawTypeResponse] = Field(default_factory=list)
    pending_raw_type_suggestions: list[RawTypeSuggestionItemResponse] = Field(default_factory=list)
    recommended_next_action: AgentRecommendedActionResponse
    blocking_conditions: list[AgentBlockingConditionResponse] = Field(default_factory=list)
    available_next_tools: list[str] = Field(default_factory=list)


class AgentChangeDecisionProposalRequest(BaseModel):
    change_id: int = Field(ge=1)

    model_config = {"extra": "forbid"}


class AgentSourceRecoveryProposalRequest(BaseModel):
    source_id: int = Field(ge=1)

    model_config = {"extra": "forbid"}


class AgentFamilyRelinkPreviewProposalRequest(BaseModel):
    raw_type_id: int = Field(ge=1)
    family_id: int = Field(ge=1)

    model_config = {"extra": "forbid"}


class AgentProposalResponse(BaseModel):
    proposal_id: int
    owner_user_id: int
    proposal_type: AgentProposalTypeLiteral
    status: AgentProposalStatusLiteral
    target_kind: str
    target_id: str
    summary: str
    summary_code: str
    reason: str
    reason_code: str
    risk_level: AgentRiskLevelLiteral
    confidence: float
    suggested_action: str
    origin_kind: str
    origin_label: str
    origin_request_id: str | None = None
    lifecycle_code: str
    execution_mode: AgentExecutionModeLiteral
    execution_mode_code: str
    next_step_code: str
    can_create_ticket: bool
    suggested_payload: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)
    target_snapshot: dict = Field(default_factory=dict)
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ApprovalTicketCreateRequest(BaseModel):
    proposal_id: int = Field(ge=1)
    channel: str = Field(default="web", min_length=1, max_length=32)

    model_config = {"extra": "forbid"}


class ApprovalTicketConfirmRequest(BaseModel):
    model_config = {"extra": "forbid"}


class ApprovalTicketCancelRequest(BaseModel):
    model_config = {"extra": "forbid"}


class ApprovalTicketResponse(BaseModel):
    ticket_id: str
    proposal_id: int
    owner_user_id: int
    channel: str
    action_type: str
    target_kind: str
    target_id: str
    payload: dict = Field(default_factory=dict)
    payload_hash: str
    target_snapshot: dict = Field(default_factory=dict)
    risk_level: AgentRiskLevelLiteral
    origin_kind: str
    origin_label: str
    origin_request_id: str | None = None
    status: ApprovalTicketStatusLiteral
    lifecycle_code: str
    next_step_code: str
    confirm_summary_code: str
    cancel_summary_code: str
    transition_message_code: str
    social_safe_cta_code: str | None = None
    can_confirm: bool
    can_cancel: bool
    last_transition_kind: str
    last_transition_label: str
    executed_result: dict = Field(default_factory=dict)
    expires_at: datetime | None = None
    confirmed_at: datetime | None = None
    canceled_at: datetime | None = None
    executed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AgentRecentActivityItemResponse(BaseModel):
    item_kind: AgentActivityKindLiteral
    activity_id: str
    occurred_at: datetime
    owner_user_id: int
    proposal_id: int | None = None
    ticket_id: str | None = None
    status: str
    lifecycle_code: str
    next_step_code: str
    risk_level: AgentRiskLevelLiteral
    target_kind: str
    target_id: str
    summary: str
    summary_code: str
    detail: str | None = None
    detail_code: str | None = None
    origin_kind: str
    origin_label: str
    origin_request_id: str | None = None
    channel: str | None = None
    execution_mode: AgentExecutionModeLiteral | None = None
    execution_mode_code: str | None = None
    confirm_summary_code: str | None = None
    cancel_summary_code: str | None = None
    transition_message_code: str | None = None
    social_safe_cta_code: str | None = None
    can_create_ticket: bool = False
    can_confirm: bool = False
    can_cancel: bool = False
    last_transition_kind: str | None = None
    last_transition_label: str | None = None
    suggested_action: str | None = None
    action_type: str | None = None


class AgentRecentActivityResponse(BaseModel):
    generated_at: datetime
    items: list[AgentRecentActivityItemResponse] = Field(default_factory=list)


def serialize_approval_ticket(row) -> dict:
    from app.modules.agents.lifecycle import (
        ticket_can_cancel,
        ticket_can_confirm,
        ticket_cancel_summary_code,
        ticket_confirm_summary_code,
        ticket_lifecycle_code,
        ticket_next_step_code,
        ticket_social_safe_cta_code,
        ticket_transition_message_code,
    )

    return {
        "ticket_id": row.ticket_id,
        "proposal_id": row.proposal_id,
        "owner_user_id": row.user_id,
        "channel": row.channel,
        "action_type": row.action_type,
        "target_kind": row.target_kind,
        "target_id": row.target_id,
        "payload": row.payload_json or {},
        "payload_hash": row.payload_hash,
        "target_snapshot": row.target_snapshot_json or {},
        "risk_level": row.risk_level,
        "origin_kind": row.origin_kind,
        "origin_label": row.origin_label,
        "origin_request_id": row.origin_request_id,
        "status": row.status.value,
        "lifecycle_code": ticket_lifecycle_code(row),
        "next_step_code": ticket_next_step_code(row),
        "confirm_summary_code": ticket_confirm_summary_code(row),
        "cancel_summary_code": ticket_cancel_summary_code(row),
        "transition_message_code": ticket_transition_message_code(row),
        "social_safe_cta_code": ticket_social_safe_cta_code(row),
        "can_confirm": ticket_can_confirm(row),
        "can_cancel": ticket_can_cancel(row),
        "last_transition_kind": row.last_transition_kind,
        "last_transition_label": row.last_transition_label,
        "executed_result": row.executed_result_json or {},
        "expires_at": row.expires_at,
        "confirmed_at": row.confirmed_at,
        "canceled_at": row.canceled_at,
        "executed_at": row.executed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def serialize_agent_proposal(row) -> dict:
    from app.modules.agents.lifecycle import (
        proposal_can_create_ticket,
        proposal_execution_mode,
        proposal_execution_mode_code,
        proposal_lifecycle_code,
        proposal_next_step_code,
    )

    return {
        "proposal_id": row.id,
        "owner_user_id": row.user_id,
        "proposal_type": row.proposal_type.value,
        "status": row.status.value,
        "target_kind": row.target_kind,
        "target_id": row.target_id,
        "summary": row.summary,
        "summary_code": row.summary_code,
        "reason": row.reason,
        "reason_code": row.reason_code,
        "risk_level": row.risk_level,
        "confidence": row.confidence,
        "suggested_action": row.suggested_action,
        "origin_kind": row.origin_kind,
        "origin_label": row.origin_label,
        "origin_request_id": row.origin_request_id,
        "lifecycle_code": proposal_lifecycle_code(row),
        "execution_mode": proposal_execution_mode(row),
        "execution_mode_code": proposal_execution_mode_code(row),
        "next_step_code": proposal_next_step_code(row),
        "can_create_ticket": proposal_can_create_ticket(row),
        "suggested_payload": row.payload_json or {},
        "context": row.context_json or {},
        "target_snapshot": row.target_snapshot_json or {},
        "expires_at": row.expires_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


__all__ = [
    "AgentRecentActivityItemResponse",
    "AgentRecentActivityResponse",
    "AgentBlockingConditionResponse",
    "AgentChangeDecisionProposalRequest",
    "AgentChangeContextResponse",
    "AgentFamilyRelinkPreviewProposalRequest",
    "AgentFamilyContextResponse",
    "AgentProposalResponse",
    "AgentRecommendedActionResponse",
    "AgentSourceRecoveryProposalRequest",
    "AgentSourceContextResponse",
    "AgentWorkspaceContextResponse",
    "ApprovalTicketCancelRequest",
    "ApprovalTicketConfirmRequest",
    "ApprovalTicketCreateRequest",
    "ApprovalTicketResponse",
    "serialize_approval_ticket",
    "serialize_agent_proposal",
]
