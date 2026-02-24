from __future__ import annotations

from typing import Any
from typing import Literal

from datetime import datetime

from pydantic import BaseModel


class ChangeResponse(BaseModel):
    id: int
    input_id: int
    event_uid: str
    change_type: str
    detected_at: datetime
    before_json: dict | None
    after_json: dict | None
    delta_seconds: int | None
    before_snapshot_id: int | None
    after_snapshot_id: int
    evidence_keys: dict[str, Any] | None
    before_raw_evidence_key: dict[str, Any] | None
    after_raw_evidence_key: dict[str, Any] | None
    viewed_at: datetime | None
    viewed_note: str | None


class ChangeSummarySide(BaseModel):
    value_time: datetime | None
    source_label: str | None
    source_type: Literal["ics", "email"] | None
    source_observed_at: datetime | None


class ChangeSummary(BaseModel):
    old: ChangeSummarySide
    new: ChangeSummarySide


class ChangeFeedResponse(ChangeResponse):
    user_id: int
    user_notify_email: str | None
    input_type: str
    term_id: int | None
    term_code: str | None
    term_label: str | None
    term_scope: str
    priority_rank: int
    priority_label: str
    notification_state: str | None
    deliver_after: datetime | None
    change_summary: ChangeSummary


class ChangeViewedUpdateRequest(BaseModel):
    viewed: bool
    note: str | None = None
