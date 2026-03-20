from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.modules.common.event_display import UserFacingEventResponse
from app.modules.common.course_identity_schemas import CourseIdentityResponse


class ManualEventWriteRequest(BaseModel):
    family_id: int = Field(ge=1)
    event_name: str = Field(min_length=1, max_length=512)
    raw_type: str | None = Field(default=None, max_length=128)
    ordinal: int | None = Field(default=None, ge=1, le=999)
    due_date: date
    due_time: time | None = None
    time_precision: Literal["date_only", "datetime"] = "datetime"
    reason: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}

    @field_validator("event_name", "raw_type", "reason", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        return cleaned or None

    @field_validator("time_precision", mode="before")
    @classmethod
    def _normalize_time_precision(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().lower() == "date_only":
            return "date_only"
        return "datetime"


class ManualEventResponse(CourseIdentityResponse):
    entity_uid: str
    lifecycle: Literal["active", "removed"]
    manual_support: bool
    family_id: int | None = None
    family_name: str
    raw_type: str | None = None
    event_name: str | None = None
    ordinal: int | None = None
    due_date: str | None = None
    due_time: str | None = None
    time_precision: Literal["date_only", "datetime"] | str
    event: UserFacingEventResponse | None = None
    created_at: datetime
    updated_at: datetime


class ManualEventMutationResponse(BaseModel):
    applied: bool
    idempotent: bool
    change_id: int | None
    entity_uid: str
    lifecycle: Literal["active", "removed"]
    event: ManualEventResponse | None = None


__all__ = [
    "ManualEventMutationResponse",
    "ManualEventResponse",
    "ManualEventWriteRequest",
]
