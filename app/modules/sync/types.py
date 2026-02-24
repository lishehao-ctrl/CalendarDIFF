from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class FetchResult:
    content: bytes | None
    etag: str | None
    fetched_at_utc: datetime
    last_modified: str | None = None
    status_code: int = 200
    not_modified: bool = False


@dataclass(frozen=True)
class RawICSEvent:
    uid: str | None
    summary: str
    description: str
    dtstart: datetime
    dtend: datetime


@dataclass(frozen=True)
class CanonicalEventInput:
    uid: str
    course_label: str
    title: str
    start_at_utc: datetime
    end_at_utc: datetime
