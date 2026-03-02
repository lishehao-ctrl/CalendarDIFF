from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


EmailRoute = Literal["drop", "archive", "review"]


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
