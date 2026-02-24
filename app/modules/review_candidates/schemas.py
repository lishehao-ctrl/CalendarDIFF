from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ReviewCandidateStatus = Literal["pending", "applied", "dismissed", "failed"]


class ReviewCandidateResponse(BaseModel):
    id: int
    user_id: int
    input_id: int
    gmail_message_id: str
    source_change_id: int | None
    status: ReviewCandidateStatus
    rule_version: str
    confidence: float
    proposed_event_type: str | None
    proposed_due_at: datetime | None
    proposed_title: str | None
    proposed_course_hint: str | None
    reasons: list[str]
    raw_extract: dict
    subject: str | None
    from_header: str | None
    snippet: str | None
    applied_change_id: int | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    applied_at: datetime | None
    dismissed_at: datetime | None


class ApplyReviewCandidateRequest(BaseModel):
    target_input_id: int = Field(ge=1)
    target_event_uid: str = Field(min_length=1)
    applied_due_at: datetime | None = None
    note: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}


class DismissReviewCandidateRequest(BaseModel):
    note: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}


class ApplyReviewCandidateResponse(BaseModel):
    candidate: ReviewCandidateResponse
    applied_change_id: int
    notification_state: str | None


class DismissReviewCandidateResponse(BaseModel):
    candidate: ReviewCandidateResponse
