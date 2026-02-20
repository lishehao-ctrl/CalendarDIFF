from __future__ import annotations

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
