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
