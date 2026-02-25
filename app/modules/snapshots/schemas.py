from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SnapshotResponse(BaseModel):
    id: int
    input_id: int
    retrieved_at: datetime
    content_hash: str
    event_count: int
    has_evidence: bool
    evidence_kind: str | None
