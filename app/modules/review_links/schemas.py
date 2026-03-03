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
