from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.modules.changes.schemas import ChangeItemResponse, ChangesWorkbenchSummaryResponse
from app.modules.common.structured_copy import render_structured_text
from app.modules.families.schemas import (
    CourseRawTypeResponse,
    CourseWorkItemFamilyResponse,
    RawTypeSuggestionItemResponse,
)
from app.modules.sources.schemas import InputSourceResponse, SourceObservabilityResponse, SyncRequestStatusResponse

AgentRiskLevelLiteral = Literal["low", "medium", "high"]
AgentConditionSeverityLiteral = Literal["info", "warning", "blocking"]
AgentProposalTypeLiteral = Literal["change_decision", "source_recovery", "family_relink_preview", "label_learning_commit", "proposal_edit_commit"]
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
    language_code: str
    language_resolution_source: str
    summary: ChangesWorkbenchSummaryResponse
    top_pending_changes: list[ChangeItemResponse]
    recommended_next_action: AgentRecommendedActionResponse
    blocking_conditions: list[AgentBlockingConditionResponse] = Field(default_factory=list)
    available_next_tools: list[str] = Field(default_factory=list)


class AgentChangeContextResponse(BaseModel):
    generated_at: datetime
    language_code: str
    language_resolution_source: str
    change: ChangeItemResponse
    recommended_next_action: AgentRecommendedActionResponse
    blocking_conditions: list[AgentBlockingConditionResponse] = Field(default_factory=list)
    available_next_tools: list[str] = Field(default_factory=list)


class AgentSourceContextResponse(BaseModel):
    generated_at: datetime
    language_code: str
    language_resolution_source: str
    source: InputSourceResponse
    observability: SourceObservabilityResponse
    active_sync_request: SyncRequestStatusResponse | None = None
    recommended_next_action: AgentRecommendedActionResponse
    blocking_conditions: list[AgentBlockingConditionResponse] = Field(default_factory=list)
    available_next_tools: list[str] = Field(default_factory=list)


class AgentFamilyContextResponse(BaseModel):
    generated_at: datetime
    language_code: str
    language_resolution_source: str
    family: CourseWorkItemFamilyResponse
    raw_types: list[CourseRawTypeResponse] = Field(default_factory=list)
    pending_raw_type_suggestions: list[RawTypeSuggestionItemResponse] = Field(default_factory=list)
    recommended_next_action: AgentRecommendedActionResponse
    blocking_conditions: list[AgentBlockingConditionResponse] = Field(default_factory=list)
    available_next_tools: list[str] = Field(default_factory=list)


class AgentChangeDecisionProposalRequest(BaseModel):
    change_id: int = Field(ge=1)
    language_code: str | None = Field(default=None, max_length=16)

    model_config = {"extra": "forbid"}


class AgentSourceRecoveryProposalRequest(BaseModel):
    source_id: int = Field(ge=1)
    language_code: str | None = Field(default=None, max_length=16)

    model_config = {"extra": "forbid"}


class AgentFamilyRelinkPreviewProposalRequest(BaseModel):
    raw_type_id: int = Field(ge=1)
    family_id: int = Field(ge=1)
    language_code: str | None = Field(default=None, max_length=16)

    model_config = {"extra": "forbid"}


class AgentFamilyRelinkCommitProposalRequest(BaseModel):
    raw_type_id: int = Field(ge=1)
    family_id: int = Field(ge=1)
    language_code: str | None = Field(default=None, max_length=16)

    model_config = {"extra": "forbid"}


class AgentLabelLearningCommitProposalRequest(BaseModel):
    change_id: int = Field(ge=1)
    family_id: int = Field(ge=1)
    language_code: str | None = Field(default=None, max_length=16)

    model_config = {"extra": "forbid"}


class AgentChangeEditCommitPatchRequest(BaseModel):
    event_name: str | None = Field(default=None, max_length=512)
    due_date: date | None = None
    due_time: str | None = Field(default=None, max_length=32)
    time_precision: Literal["date_only", "datetime"] | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_non_empty_patch(self) -> "AgentChangeEditCommitPatchRequest":
        if not self.model_fields_set:
            raise ValueError("patch must include at least one editable proposal field")
        return self


class AgentChangeEditCommitProposalRequest(BaseModel):
    change_id: int = Field(ge=1)
    patch: AgentChangeEditCommitPatchRequest
    language_code: str | None = Field(default=None, max_length=16)

    model_config = {"extra": "forbid"}


class AgentProposalResponse(BaseModel):
    proposal_id: int
    language_code: str
    language_resolution_source: str
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
    language_code: str | None = Field(default=None, max_length=16)

    model_config = {"extra": "forbid"}


class ApprovalTicketConfirmRequest(BaseModel):
    language_code: str | None = Field(default=None, max_length=16)
    model_config = {"extra": "forbid"}


class ApprovalTicketCancelRequest(BaseModel):
    language_code: str | None = Field(default=None, max_length=16)
    model_config = {"extra": "forbid"}


class ApprovalTicketResponse(BaseModel):
    ticket_id: str
    language_code: str
    language_resolution_source: str
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
    confirm_summary: str
    cancel_summary: str
    transition_message: str
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
    language_code: str
    language_resolution_source: str
    items: list[AgentRecentActivityItemResponse] = Field(default_factory=list)


def serialize_approval_ticket(
    row,
    *,
    language_code: str | None = None,
    language_resolution_source: str | None = None,
) -> dict:
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

    ticket_copy = _render_approval_ticket_copy(row=row, language_code=language_code)
    return {
        "ticket_id": row.ticket_id,
        "language_code": language_code or "en",
        "language_resolution_source": language_resolution_source or "default",
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
        "confirm_summary": ticket_copy["confirm_summary"],
        "cancel_summary": ticket_copy["cancel_summary"],
        "transition_message": ticket_copy["transition_message"],
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


def serialize_agent_proposal(
    row,
    *,
    language_code: str | None = None,
    language_resolution_source: str | None = None,
) -> dict:
    from app.modules.agents.lifecycle import (
        proposal_can_create_ticket,
        proposal_execution_mode,
        proposal_execution_mode_code,
        proposal_lifecycle_code,
        proposal_next_step_code,
    )

    summary = render_structured_text(
        code=row.summary_code,
        language_code=language_code,
        params=_proposal_summary_params(row=row, language_code=language_code),
        fallback=row.summary,
    )
    reason = render_structured_text(
        code=_proposal_reason_code(row),
        language_code=language_code,
        params=_proposal_reason_params(row),
        fallback=row.reason,
    )

    return {
        "proposal_id": row.id,
        "language_code": language_code or "en",
        "language_resolution_source": language_resolution_source or "default",
        "owner_user_id": row.user_id,
        "proposal_type": row.proposal_type.value,
        "status": row.status.value,
        "target_kind": row.target_kind,
        "target_id": row.target_id,
        "summary": summary,
        "summary_code": row.summary_code,
        "reason": reason,
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


def _proposal_summary_params(*, row, language_code: str | None) -> dict:
    stored = getattr(row, "summary_params_json", None)
    if isinstance(stored, dict) and stored:
        return dict(stored)
    proposal_type = getattr(row.proposal_type, "value", "")
    if proposal_type == "change_decision":
        review_bucket = _proposal_review_bucket(row)
        if review_bucket:
            fallback = "Initial Review" if review_bucket == "initial_review" else "Replay Review"
            return {
                "lane_label": render_structured_text(
                    code=f"agents.lane.{review_bucket}",
                    language_code=language_code,
                    fallback=fallback,
                )
            }
    if proposal_type == "source_recovery":
        provider = _proposal_provider(row)
        if provider:
            return {"provider_label": _provider_label(provider)}
    return {}


def _proposal_reason_params(row) -> dict:
    stored = getattr(row, "reason_params_json", None)
    if isinstance(stored, dict) and stored:
        return dict(stored)
    context = row.context_json if isinstance(row.context_json, dict) else {}
    recommendation = context.get("recommended_next_action")
    if isinstance(recommendation, dict) and isinstance(recommendation.get("reason_params"), dict) and recommendation.get("reason_params"):
        return recommendation["reason_params"]
    operator_guidance = context.get("operator_guidance")
    if isinstance(operator_guidance, dict) and isinstance(operator_guidance.get("message_params"), dict) and operator_guidance.get("message_params"):
        return operator_guidance["message_params"]
    return {}


def _proposal_reason_code(row) -> str:
    reason_code = str(getattr(row, "reason_code", "") or "")
    if "." in reason_code:
        return reason_code

    context = row.context_json if isinstance(row.context_json, dict) else {}
    operator_guidance = context.get("operator_guidance")
    if isinstance(operator_guidance, dict):
        message_code = operator_guidance.get("message_code")
        if isinstance(message_code, str) and message_code:
            return message_code
    source_recovery = context.get("source_recovery")
    if isinstance(source_recovery, dict):
        impact_code = source_recovery.get("impact_code")
        if isinstance(impact_code, str) and impact_code:
            return impact_code
    return reason_code


def _proposal_review_bucket(row) -> str | None:
    context = row.context_json if isinstance(row.context_json, dict) else {}
    target_snapshot = row.target_snapshot_json if isinstance(row.target_snapshot_json, dict) else {}
    for payload in (context, target_snapshot):
        review_bucket = payload.get("review_bucket")
        if isinstance(review_bucket, str) and review_bucket:
            return review_bucket
    return None


def _proposal_provider(row) -> str | None:
    context = row.context_json if isinstance(row.context_json, dict) else {}
    target_snapshot = row.target_snapshot_json if isinstance(row.target_snapshot_json, dict) else {}
    payload = row.payload_json if isinstance(row.payload_json, dict) else {}
    for candidate in (context.get("provider"), target_snapshot.get("provider"), payload.get("provider")):
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _provider_label(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized == "gmail":
        return "Gmail"
    if normalized == "ics":
        return "Canvas ICS"
    return provider.strip().title() or "Source"


def _render_approval_ticket_copy(*, row, language_code: str | None) -> dict:
    action_label = render_structured_text(
        code=f"agents.ticket.action.{row.action_type}",
        language_code=language_code,
        fallback=row.action_type.replace("_", " "),
    )
    return {
        "confirm_summary": render_structured_text(
            code="agents.ticket.confirm.summary",
            language_code=language_code,
            params={"action_label": action_label},
            fallback=f"Confirm {action_label}.",
        ),
        "cancel_summary": render_structured_text(
            code="agents.ticket.cancel.summary",
            language_code=language_code,
            params={"action_label": action_label},
            fallback=f"Cancel {action_label}.",
        ),
        "transition_message": render_structured_text(
            code=f"agents.ticket.transition.{row.status.value}",
            language_code=language_code,
            params={"action_label": action_label},
            fallback=f"{action_label} {row.status.value}.",
        ),
        "activity_summary": render_structured_text(
            code=f"agents.activity.ticket.summary.{row.status.value}",
            language_code=language_code,
            params={"action_label": action_label},
            fallback=f"{action_label} {row.status.value}.",
        ),
        "activity_detail": render_structured_text(
            code=f"agents.activity.ticket.detail.{row.status.value}",
            language_code=language_code,
            params={"action_label": action_label},
            fallback=f"{action_label} {row.status.value}.",
        ),
    }


__all__ = [
    "AgentRecentActivityItemResponse",
    "AgentRecentActivityResponse",
    "AgentBlockingConditionResponse",
    "AgentChangeEditCommitPatchRequest",
    "AgentChangeEditCommitProposalRequest",
    "AgentChangeDecisionProposalRequest",
    "AgentChangeContextResponse",
    "AgentFamilyRelinkPreviewProposalRequest",
    "AgentFamilyRelinkCommitProposalRequest",
    "AgentLabelLearningCommitProposalRequest",
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
    "_render_approval_ticket_copy",
    "serialize_approval_ticket",
    "serialize_agent_proposal",
]
