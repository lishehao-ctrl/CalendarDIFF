from __future__ import annotations

from typing import Literal

from datetime import datetime

from pydantic import BaseModel


class ChangeResponse(BaseModel):
    id: int
    source_id: int
    event_uid: str
    change_type: str
    detected_at: datetime
    before_json: dict | None
    after_json: dict | None
    delta_seconds: int | None
    before_snapshot_id: int | None
    after_snapshot_id: int | None
    has_before_evidence: bool
    has_after_evidence: bool
    before_evidence_kind: str | None
    after_evidence_kind: str | None
    viewed_at: datetime | None
    viewed_note: str | None


class ChangeSummarySide(BaseModel):
    value_time: datetime | None
    source_label: str | None
    source_kind: Literal["calendar", "email"] | None
    source_observed_at: datetime | None


class ChangeSummary(BaseModel):
    old: ChangeSummarySide
    new: ChangeSummarySide


class ChangeFeedResponse(ChangeResponse):
    source_kind: str
    priority_rank: int
    priority_label: str
    notification_state: str | None
    deliver_after: datetime | None
    change_summary: ChangeSummary


class ChangeViewedUpdateRequest(BaseModel):
    viewed: bool
    note: str | None = None


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
