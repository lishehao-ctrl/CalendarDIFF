from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CalendarExtractedEvent(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    start_at: str = Field(min_length=1, max_length=128)
    end_at: str = Field(min_length=1, max_length=128)
    uid: str | None = Field(default=None, max_length=255)
    course_label: str | None = Field(default=None, max_length=128)
    raw_confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    model_config = {"extra": "forbid"}


class CalendarParserResponse(BaseModel):
    events: list[CalendarExtractedEvent] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class GmailExtractedMessage(BaseModel):
    message_id: str | None = Field(default=None, max_length=255)
    subject: str | None = Field(default=None, max_length=512)
    event_type: Literal[
        "deadline",
        "exam",
        "schedule_change",
        "assignment",
        "action_required",
        "announcement",
        "grade",
        "other",
    ] | None = None
    due_at: str | None = Field(default=None, max_length=128)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    raw_extract: dict = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @field_validator("message_id", "subject", "due_at", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @field_validator("event_type", mode="before")
    @classmethod
    def _normalize_event_type(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip().lower()
            return cleaned or None
        return value


class GmailParserResponse(BaseModel):
    messages: list[GmailExtractedMessage] = Field(default_factory=list)

    model_config = {"extra": "forbid"}
