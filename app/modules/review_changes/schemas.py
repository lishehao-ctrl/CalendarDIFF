from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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


class EvidencePreviewEvent(BaseModel):
    uid: str | None
    summary: str | None
    dtstart: str | None
    dtend: str | None
    location: str | None
    description: str | None


class EvidencePreviewResponse(BaseModel):
    side: Literal["before", "after"]
    content_type: str
    truncated: bool
    filename: str
    event_count: int
    events: list[EvidencePreviewEvent]
    preview_text: str | None = None


class ManualCorrectionTargetRequest(BaseModel):
    change_id: int | None = Field(default=None, ge=1)
    event_uid: str | None = Field(default=None, max_length=255)

    model_config = {"extra": "forbid"}


class ManualCorrectionPatchRequest(BaseModel):
    due_at: str = Field(min_length=1, max_length=128)
    title: str | None = Field(default=None, max_length=512)
    course_label: str | None = Field(default=None, max_length=64)

    model_config = {"extra": "forbid"}


class ManualCorrectionRequest(BaseModel):
    target: ManualCorrectionTargetRequest
    patch: ManualCorrectionPatchRequest
    reason: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}


class ManualCorrectionEventPayload(BaseModel):
    uid: str
    title: str
    course_label: str
    start_at_utc: datetime
    end_at_utc: datetime


class ManualCorrectionPreviewResponse(BaseModel):
    event_uid: str
    base: ManualCorrectionEventPayload
    candidate_after: ManualCorrectionEventPayload
    delta_seconds: int | None
    will_reject_pending_change_ids: list[int]
    idempotent: bool


class ManualCorrectionApplyResponse(BaseModel):
    applied: bool
    idempotent: bool
    correction_change_id: int | None
    event_uid: str
    rejected_pending_change_ids: list[int]
    event: ManualCorrectionEventPayload
