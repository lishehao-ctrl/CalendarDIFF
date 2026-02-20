from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class ChangeDigestItem:
    event_uid: str
    change_type: str
    course_label: str
    title: str
    before_start_at_utc: str | None
    after_start_at_utc: str | None
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
        source_name: str,
        source_id: int,
        items: list[ChangeDigestItem],
    ) -> SendResult:
        ...
