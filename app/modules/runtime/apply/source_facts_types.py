from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CanonicalEventInput:
    uid: str
    course_label: str
    title: str
    start_at_utc: datetime
    end_at_utc: datetime


__all__ = ["CanonicalEventInput"]
