from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ReviewSourceRef(BaseModel):
    source_id: int
    source_kind: str | None = None
    provider: str | None = None
    external_event_id: str | None = None
    confidence: float | None = None


class ChangeSummarySide(BaseModel):
    value_time: datetime | None = None
    source_label: str | None = None
    source_kind: Literal["calendar", "email"] | None = None
    source_observed_at: datetime | None = None


class ChangeSummary(BaseModel):
    old: ChangeSummarySide
    new: ChangeSummarySide


class ReviewChangeItemResponse(BaseModel):
    id: int
    event_uid: str
    change_type: str
    detected_at: datetime
    review_status: Literal["pending", "approved", "rejected"]
    before_json: dict | None
    after_json: dict | None
    proposal_merge_key: str | None
    proposal_sources: list[ReviewSourceRef]
    source_id: int | None
    viewed_at: datetime | None
    viewed_note: str | None
    reviewed_at: datetime | None
    review_note: str | None
    source_kind: str | None = None
    priority_rank: int | None = None
    priority_label: str | None = None
    notification_state: str | None = None
    deliver_after: datetime | None = None
    change_summary: ChangeSummary | None = None


class ReviewChangeViewRequest(BaseModel):
    viewed: bool
    note: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}


class ReviewDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}


class ReviewDecisionResponse(BaseModel):
    id: int
    review_status: Literal["pending", "approved", "rejected"]
    reviewed_at: datetime | None
    review_note: str | None
    idempotent: bool


class ReviewBatchDecisionRequest(BaseModel):
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


class ReviewBatchDecisionItemResult(BaseModel):
    id: int
    ok: bool
    review_status: Literal["pending", "approved", "rejected"] | None
    idempotent: bool
    reviewed_at: datetime | None
    review_note: str | None
    error_code: Literal["not_found", "invalid_state"] | None
    error_detail: str | None


class ReviewBatchDecisionResponse(BaseModel):
    decision: Literal["approve", "reject"]
    total_requested: int
    succeeded: int
    failed: int
    results: list[ReviewBatchDecisionItemResult]


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
    title: str | None = None
    course_label: str | None = None
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


class ReviewEditTargetRequest(BaseModel):
    change_id: int | None = Field(default=None, ge=1)
    event_uid: str | None = Field(default=None, max_length=255)

    model_config = {"extra": "forbid"}


class ReviewEditPatchRequest(BaseModel):
    due_at: str = Field(min_length=1, max_length=128)
    title: str | None = Field(default=None, max_length=512)
    course_label: str | None = Field(default=None, max_length=64)

    model_config = {"extra": "forbid"}


class ReviewEditRequest(BaseModel):
    mode: Literal["proposal", "canonical"]
    target: ReviewEditTargetRequest
    patch: ReviewEditPatchRequest
    reason: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}


class ReviewEditEventPayload(BaseModel):
    uid: str
    title: str
    course_label: str
    start_at_utc: datetime
    end_at_utc: datetime


class ReviewEditPreviewResponse(BaseModel):
    mode: Literal["proposal", "canonical"]
    event_uid: str
    change_id: int | None = None
    proposal_change_type: Literal["created", "due_changed"] | None = None
    base: ReviewEditEventPayload
    candidate_after: ReviewEditEventPayload
    delta_seconds: int | None
    will_reject_pending_change_ids: list[int]
    idempotent: bool


class ReviewEditApplyResponse(BaseModel):
    mode: Literal["proposal", "canonical"]
    applied: bool
    idempotent: bool
    event_uid: str
    edited_change_id: int | None = None
    canonical_edit_change_id: int | None = None
    rejected_pending_change_ids: list[int]
    event: ReviewEditEventPayload


class LabelLearningFamilyOption(BaseModel):
    id: int
    course_key: str
    canonical_label: str
    aliases: list[str]


class LabelLearningPreviewResponse(BaseModel):
    change_id: int
    course_key: str | None
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
    course_key: str | None
    raw_label: str | None
    family_id: int | None
    canonical_label: str | None
    approved_change_id: int | None = None
