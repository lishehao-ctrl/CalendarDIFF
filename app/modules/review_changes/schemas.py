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
