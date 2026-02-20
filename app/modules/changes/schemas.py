from __future__ import annotations

from typing import Any

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
    after_snapshot_id: int
    evidence_keys: dict[str, Any] | None
    before_raw_evidence_key: dict[str, Any] | None
    after_raw_evidence_key: dict[str, Any] | None
