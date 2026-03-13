from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.common.event_display import EventDisplay


@dataclass(frozen=True)
class ChangeDigestItem:
    entity_uid: str
    change_type: str
    before_display: EventDisplay | None
    after_display: EventDisplay | None
    before_due_at: str | None
    after_due_at: str | None
    before_time_precision: str
    after_time_precision: str
    delta_seconds: int | None
    detected_at: datetime
    evidence_path: str | None


@dataclass(frozen=True)
class SendResult:
    success: bool
    error: str | None = None


class Notifier(Protocol):
    def send_changes_digest(
        self,
        to_email: str,
        review_label: str,
        user_id: int,
        items: list[ChangeDigestItem],
        timezone_name: str | None = None,
    ) -> SendResult:
        ...
