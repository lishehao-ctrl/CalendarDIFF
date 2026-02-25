from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


EmailRoute = Literal["drop", "archive", "notify", "review"]


class EmailQueueActionItem(BaseModel):
    action: str | None
    due_iso: str | None
    where: str | None


class EmailMatchedSnippet(BaseModel):
    rule: str
    snippet: str


class EmailQueueRuleAnalysis(BaseModel):
    event_flags: dict[str, bool]
    matched_snippets: list[EmailMatchedSnippet]
    drop_reason_codes: list[str]


class EmailQueueFlags(BaseModel):
    viewed: bool
    notified: bool
    viewed_at: datetime | None
    notified_at: datetime | None


class EmailQueueItemResponse(BaseModel):
    email_id: str
    from_addr: str | None
    subject: str | None
    date_rfc822: str | None
    route: EmailRoute
    event_type: str | None
    confidence: float
    reasons: list[str]
    course_hints: list[str]
    action_items: list[EmailQueueActionItem]
    rule_analysis: EmailQueueRuleAnalysis
    flags: EmailQueueFlags


class UpdateEmailRouteRequest(BaseModel):
    route: EmailRoute

    model_config = {"extra": "forbid"}


class UpdateEmailRouteResponse(BaseModel):
    email_id: str
    route: EmailRoute
    routed_at: datetime
    notified_at: datetime | None


class MarkEmailViewedResponse(BaseModel):
    email_id: str
    viewed_at: datetime


class ApplyEmailReviewRequest(BaseModel):
    mode: Literal["create_new", "update_existing"] = "create_new"
    target_input_id: int | None = Field(default=None, ge=1)
    target_event_uid: str | None = Field(default=None, min_length=1)
    applied_due_at: datetime | None = None
    note: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}


class ApplyEmailReviewResponse(BaseModel):
    task_id: int
    change_id: int
