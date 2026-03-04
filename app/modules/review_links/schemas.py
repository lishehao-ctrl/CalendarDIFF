from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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
