from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.common.event_display import EventDisplayResponse, UserFacingEventResponse
from app.modules.common.payload_schemas import SemanticEventDraft
from app.modules.sources.schemas import SourceOperatorActionLiteral, SourceOperatorSeverityLiteral


class ChangeSourceRefResponse(BaseModel):
    source_id: int
    source_kind: str | None = None
    provider: str | None = None
    external_event_id: str | None = None
    confidence: float | None = None


class ChangePrimarySourceRefResponse(BaseModel):
    source_id: int
    source_kind: str | None = None
    provider: str | None = None
    external_event_id: str | None = None


class ChangeSummarySide(BaseModel):
    value_time: datetime | None = None
    source_label: str | None = None
    source_kind: Literal["calendar", "email"] | None = None
    source_observed_at: datetime | None = None


class ChangeSummary(BaseModel):
    old: ChangeSummarySide
    new: ChangeSummarySide


class ChangeItemResponse(BaseModel):
    id: int
    entity_uid: str
    change_type: str
    change_origin: str
    intake_phase: Literal["baseline", "replay"] = "replay"
    review_bucket: Literal["initial_review", "changes"] = "changes"
    detected_at: datetime
    review_status: Literal["pending", "approved", "rejected"]
    before_display: EventDisplayResponse | None = None
    after_display: EventDisplayResponse | None = None
    before_event: UserFacingEventResponse | None = None
    after_event: UserFacingEventResponse | None = None
    primary_source: ChangePrimarySourceRefResponse | None = None
    proposal_sources: list[ChangeSourceRefResponse]
    viewed_at: datetime | None
    viewed_note: str | None
    reviewed_at: datetime | None
    review_note: str | None
    priority_rank: int | None = None
    priority_label: str | None = None
    notification_state: str | None = None
    deliver_after: datetime | None = None
    change_summary: ChangeSummary | None = None


class ChangeViewRequest(BaseModel):
    viewed: bool
    note: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}


class ChangeDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}


class ChangeDecisionResponse(BaseModel):
    id: int
    review_status: Literal["pending", "approved", "rejected"]
    reviewed_at: datetime | None
    review_note: str | None
    idempotent: bool


class ChangeBatchDecisionRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}

    @field_validator("ids")
    @classmethod
    def _validate_ids_positive(cls, value: list[int]) -> list[int]:
        if any((not isinstance(item, int) or item <= 0) for item in value):
            raise ValueError("ids must contain positive integers")
        return value


class ChangeBatchDecisionItemResult(BaseModel):
    id: int
    ok: bool
    review_status: Literal["pending", "approved", "rejected"] | None
    idempotent: bool
    reviewed_at: datetime | None
    review_note: str | None
    error_code: Literal["not_found", "invalid_state"] | None
    error_detail: str | None


class ChangeBatchDecisionResponse(BaseModel):
    decision: Literal["approve", "reject"]
    total_requested: int
    succeeded: int
    failed: int
    results: list[ChangeBatchDecisionItemResult]


WorkbenchLaneLiteral = Literal["sources", "initial_review", "changes", "families"]


class ChangesWorkbenchSourcesResponse(BaseModel):
    active_count: int
    running_count: int
    queued_count: int
    attention_count: int
    blocking_count: int
    recommended_action: SourceOperatorActionLiteral
    severity: SourceOperatorSeverityLiteral
    reason_code: str
    message: str
    related_request_id: str | None = None
    progress_age_seconds: int | None = None


class ChangesWorkbenchFamiliesResponse(BaseModel):
    attention_count: int
    pending_raw_type_suggestions: int
    mappings_state: str
    last_rebuilt_at: datetime | None
    last_error: str | None


class ChangesWorkbenchManualResponse(BaseModel):
    active_event_count: int
    lane_role: Literal["fallback"] = "fallback"


class ChangesWorkbenchSummaryResponse(BaseModel):
    changes_pending: int
    baseline_review_pending: int = 0
    recommended_lane: WorkbenchLaneLiteral | None = None
    recommended_lane_reason_code: str
    recommended_action_reason: str
    sources: ChangesWorkbenchSourcesResponse
    families: ChangesWorkbenchFamiliesResponse
    manual: ChangesWorkbenchManualResponse
    generated_at: datetime


class EvidencePreviewEvent(BaseModel):
    uid: str | None
    summary: str | None
    dtstart: str | None
    dtend: str | None
    location: str | None
    description: str | None
    url: str | None = None


class EvidencePreviewStructuredItem(BaseModel):
    uid: str | None = None
    event_display: EventDisplayResponse | None = None
    source_title: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    location: str | None = None
    description: str | None = None
    url: str | None = None
    sender: str | None = None
    snippet: str | None = None
    internal_date: str | None = None
    thread_id: str | None = None


class EvidencePreviewResponse(BaseModel):
    side: Literal["before", "after"]
    content_type: str
    truncated: bool
    filename: str
    provider: str | None = None
    structured_kind: Literal["ics_event", "gmail_event", "generic"] = "generic"
    structured_items: list[EvidencePreviewStructuredItem] = Field(default_factory=list)
    event_count: int
    events: list[EvidencePreviewEvent]
    preview_text: str | None = None


class ChangeEditTargetRequest(BaseModel):
    change_id: int | None = Field(default=None, ge=1)
    entity_uid: str | None = Field(default=None, max_length=255)

    model_config = {"extra": "forbid"}


class ChangeEditPatchRequest(BaseModel):
    event_name: str | None = Field(default=None, max_length=512)
    due_date: date | None = None
    due_time: str | None = Field(default=None, max_length=32)
    time_precision: Literal["date_only", "datetime"] | None = None
    course_dept: str | None = Field(default=None, max_length=16)
    course_number: int | None = Field(default=None, ge=0, le=9999)
    course_suffix: str | None = Field(default=None, max_length=8)
    course_quarter: Literal["WI", "SP", "SU", "FA"] | None = None
    course_year2: int | None = Field(default=None, ge=0, le=99)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_non_empty_patch(self) -> "ChangeEditPatchRequest":
        if not self.model_fields_set:
            raise ValueError("patch must include at least one semantic field")
        return self


class ChangeEditRequest(BaseModel):
    mode: Literal["proposal", "canonical"]
    target: ChangeEditTargetRequest
    patch: ChangeEditPatchRequest
    reason: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_target_mode(self) -> "ChangeEditRequest":
        if self.mode == "proposal" and self.target.change_id is None:
            raise ValueError("proposal edits require target.change_id")
        if self.mode == "canonical" and not self.target.entity_uid:
            raise ValueError("canonical edits require target.entity_uid")
        return self


class ChangeEditContextResponse(BaseModel):
    change_id: int
    entity_uid: str
    editable_event: SemanticEventDraft


class ChangeEditPreviewResponse(BaseModel):
    mode: Literal["proposal", "canonical"]
    entity_uid: str
    change_id: int | None = None
    proposal_change_type: Literal["created", "due_changed"] | None = None
    base: UserFacingEventResponse
    candidate_after: UserFacingEventResponse
    delta_seconds: int | None
    will_reject_pending_change_ids: list[int]
    idempotent: bool


class ChangeEditApplyResponse(BaseModel):
    mode: Literal["proposal", "canonical"]
    applied: bool
    idempotent: bool
    entity_uid: str
    edited_change_id: int | None = None
    canonical_edit_change_id: int | None = None
    rejected_pending_change_ids: list[int]
    event: UserFacingEventResponse


class LabelLearningFamilyOption(BaseModel):
    id: int
    course_display: str
    course_dept: str
    course_number: int
    course_suffix: str | None = None
    course_quarter: str | None = None
    course_year2: int | None = None
    canonical_label: str
    raw_types: list[str]


class LabelLearningPreviewResponse(BaseModel):
    change_id: int
    course_display: str | None
    course_dept: str | None = None
    course_number: int | None = None
    course_suffix: str | None = None
    course_quarter: str | None = None
    course_year2: int | None = None
    raw_label: str | None
    ordinal: int | None
    status: Literal["resolved", "unresolved"]
    resolved_family_id: int | None = None
    resolved_canonical_label: str | None = None
    families: list[LabelLearningFamilyOption]


class LabelLearningApplyRequest(BaseModel):
    mode: Literal["add_alias", "create_family"]
    family_id: int | None = Field(default=None, ge=1)
    canonical_label: str | None = Field(default=None, max_length=128)

    model_config = {"extra": "forbid"}


class LabelLearningApplyResponse(BaseModel):
    applied: bool
    course_display: str | None
    course_dept: str | None = None
    course_number: int | None = None
    course_suffix: str | None = None
    course_quarter: str | None = None
    course_year2: int | None = None
    raw_label: str | None
    family_id: int | None
    canonical_label: str | None
    approved_change_id: int | None = None
