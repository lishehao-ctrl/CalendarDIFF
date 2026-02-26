from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class EventListItemResponse(BaseModel):
    id: int
    input_id: int
    uid: str
    course_label: str
    title: str
    start_at_utc: datetime
    end_at_utc: datetime
    updated_at: datetime
    input_label: str
    input_type: Literal["ics", "email"]

