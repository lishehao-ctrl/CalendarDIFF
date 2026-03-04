from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LinkCandidateEntityPreview(BaseModel):
    entity_uid: str
    course_best_display: str | None = None
    course_best_strength: int | None = None


class LinkCandidateItemResponse(BaseModel):
    id: int
    source_id: int
    external_event_id: str
    proposed_entity_uid: str | None
    score: float | None
    score_breakdown: dict
    reason_code: Literal["score_band", "no_time_anchor", "low_confidence"]
    status: Literal["pending", "approved", "rejected"]
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime
    updated_at: datetime
    evidence_snapshot: dict | None = None
    proposed_entity: LinkCandidateEntityPreview | None = None


class LinkCandidateDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}


class LinkCandidateDecisionResponse(BaseModel):
    id: int
    status: Literal["pending", "approved", "rejected"]
    idempotent: bool
    block_id: int | None = None
    link_id: int | None = None


class LinkBlockItemResponse(BaseModel):
    id: int
    source_id: int
    external_event_id: str
    blocked_entity_uid: str
    note: str | None
    created_at: datetime


class LinkBlockDeleteResponse(BaseModel):
    deleted: bool
    id: int


class LinkItemResponse(BaseModel):
    id: int
    source_id: int
    source_kind: str
    external_event_id: str
    entity_uid: str
    link_origin: str
    link_score: float | None = None
    created_at: datetime
    updated_at: datetime
    signals: dict | None = None
    linked_entity: LinkCandidateEntityPreview | None = None


class LinkDeleteResponse(BaseModel):
    deleted: bool
    id: int
    block_id: int | None = None


class LinkRelinkRequest(BaseModel):
    source_id: int = Field(ge=1)
    external_event_id: str = Field(min_length=1, max_length=255)
    entity_uid: str = Field(min_length=1, max_length=128)
    clear_block: bool = True
    note: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}


class LinkRelinkResponse(BaseModel):
    link_id: int
    entity_uid: str
    source_id: int
    external_event_id: str
    cleared_blocks: int


class LinkAlertItemResponse(BaseModel):
    id: int
    source_id: int
    external_event_id: str
    entity_uid: str
    link_id: int | None
    status: Literal["pending", "dismissed", "marked_safe", "resolved"]
    reason_code: Literal["auto_link_without_canonical_change"]
    resolution_code: Literal[
        "dismissed_by_user",
        "marked_safe_by_user",
        "canonical_pending_created",
        "candidate_opened",
        "link_removed",
        "link_relinked",
    ] | None = None
    risk_level: Literal["medium"]
    evidence_snapshot: dict
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime
    updated_at: datetime
    linked_entity: LinkCandidateEntityPreview | None = None


class LinkAlertDecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}


class LinkAlertDecisionResponse(BaseModel):
    id: int
    status: Literal["pending", "dismissed", "marked_safe", "resolved"]
    idempotent: bool
    reviewed_at: datetime | None
    review_note: str | None


class ReviewItemsSummaryResponse(BaseModel):
    changes_pending: int
    link_candidates_pending: int
    link_alerts_pending: int
    generated_at: datetime


class BatchIdsDecisionBase(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}

    @field_validator("ids")
    @classmethod
    def _validate_ids_positive(cls, value: list[int]) -> list[int]:
        if any((not isinstance(item, int) or item <= 0) for item in value):
            raise ValueError("ids must contain positive integers")
        return value


class LinkAlertBatchDecisionRequest(BatchIdsDecisionBase):
    decision: Literal["dismiss", "mark_safe"]


class LinkAlertBatchDecisionItemResult(BaseModel):
    id: int
    ok: bool
    status: Literal["pending", "dismissed", "marked_safe", "resolved"] | None
    idempotent: bool
    reviewed_at: datetime | None
    review_note: str | None
    error_code: Literal["not_found"] | None
    error_detail: str | None


class LinkAlertBatchDecisionResponse(BaseModel):
    decision: Literal["dismiss", "mark_safe"]
    total_requested: int
    succeeded: int
    failed: int
    results: list[LinkAlertBatchDecisionItemResult]


class LinkCandidateBatchDecisionRequest(BatchIdsDecisionBase):
    decision: Literal["approve", "reject"]


class LinkCandidateBatchDecisionItemResult(BaseModel):
    id: int
    ok: bool
    status: Literal["pending", "approved", "rejected"] | None
    idempotent: bool
    link_id: int | None
    block_id: int | None
    error_code: Literal["not_found", "invalid_state"] | None
    error_detail: str | None


class LinkCandidateBatchDecisionResponse(BaseModel):
    decision: Literal["approve", "reject"]
    total_requested: int
    succeeded: int
    failed: int
    results: list[LinkCandidateBatchDecisionItemResult]
