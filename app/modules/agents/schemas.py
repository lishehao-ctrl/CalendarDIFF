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
AgentProposalTypeLiteral = Literal["change_decision", "source_recovery"]
AgentProposalStatusLiteral = Literal["open", "accepted", "rejected", "expired", "superseded"]
ApprovalTicketStatusLiteral = Literal["open", "executed", "canceled", "expired", "failed"]
AgentActivityKindLiteral = Literal["proposal", "ticket"]


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


class AgentProposalResponse(BaseModel):
    proposal_id: int
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
    channel: str
    action_type: str
    target_kind: str
    target_id: str
    payload: dict = Field(default_factory=dict)
    payload_hash: str
    target_snapshot: dict = Field(default_factory=dict)
    risk_level: AgentRiskLevelLiteral
    status: ApprovalTicketStatusLiteral
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
    proposal_id: int | None = None
    ticket_id: str | None = None
    status: str
    risk_level: AgentRiskLevelLiteral
    target_kind: str
    target_id: str
    summary: str
    summary_code: str
    detail: str | None = None
    detail_code: str | None = None
    channel: str | None = None
    suggested_action: str | None = None
    action_type: str | None = None


class AgentRecentActivityResponse(BaseModel):
    generated_at: datetime
    items: list[AgentRecentActivityItemResponse] = Field(default_factory=list)


def serialize_approval_ticket(row) -> dict:
    return {
        "ticket_id": row.ticket_id,
        "proposal_id": row.proposal_id,
        "channel": row.channel,
        "action_type": row.action_type,
        "target_kind": row.target_kind,
        "target_id": row.target_id,
        "payload": row.payload_json or {},
        "payload_hash": row.payload_hash,
        "target_snapshot": row.target_snapshot_json or {},
        "risk_level": row.risk_level,
        "status": row.status.value,
        "executed_result": row.executed_result_json or {},
        "expires_at": row.expires_at,
        "confirmed_at": row.confirmed_at,
        "canceled_at": row.canceled_at,
        "executed_at": row.executed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def serialize_agent_proposal(row) -> dict:
    return {
        "proposal_id": row.id,
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
