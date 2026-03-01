from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class IntegrationEvent(BaseModel):
    event_id: str = Field(min_length=8, max_length=64)
    event_type: str = Field(min_length=1, max_length=128)
    aggregate_type: str = Field(min_length=1, max_length=64)
    aggregate_id: str = Field(min_length=1, max_length=128)
    payload: dict = Field(default_factory=dict)
    available_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def new_event(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict | None = None,
) -> IntegrationEvent:
    return IntegrationEvent(
        event_id=uuid4().hex,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload or {},
    )

