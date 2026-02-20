from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SnapshotResponse(BaseModel):
    id: int
    source_id: int
    retrieved_at: datetime
    content_hash: str
    event_count: int
    raw_evidence_key: dict[str, Any] | None
