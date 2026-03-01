from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ConnectorRecord(BaseModel):
    record_type: str = Field(min_length=1, max_length=128)
    payload: dict = Field(default_factory=dict)


class ConnectorResultEnvelope(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)
    source_id: int
    provider: str = Field(min_length=1, max_length=64)
    status: str
    cursor_patch: dict = Field(default_factory=dict)
    records: list[ConnectorRecord] = Field(default_factory=list)
    fetched_at: datetime
    error_code: str | None = None
    error_message: str | None = None

