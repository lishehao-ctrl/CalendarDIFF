from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


class InputCreateRequest(BaseModel):
    url: HttpUrl

    model_config = {"extra": "forbid"}


class GmailOAuthStartRequest(BaseModel):
    label: str | None = Field(default=None, max_length=255)
    from_contains: str | None = Field(default=None, max_length=255)
    subject_keywords: list[str] | None = Field(default=None)
    model_config = {"extra": "forbid"}

    @field_validator("label", "from_contains")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("subject_keywords")
    @classmethod
    def validate_subject_keywords(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            stripped = item.strip()
            if not stripped:
                continue
            lowered = stripped.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            cleaned.append(stripped)
        return cleaned or None


class GmailOAuthStartResponse(BaseModel):
    authorization_url: str
    expires_at: datetime


class InputResponse(BaseModel):
    id: int
    type: str
    display_label: str
    provider: str | None
    gmail_label: str | None
    gmail_from_contains: str | None
    gmail_subject_keywords: list[str] | None
    gmail_account_email: str | None
    notify_email: str | None
    interval_minutes: int
    is_active: bool
    last_checked_at: datetime | None
    last_ok_at: datetime | None
    last_change_detected_at: datetime | None
    last_error_at: datetime | None
    last_email_sent_at: datetime | None
    next_check_at: datetime | None
    last_result: str | None
    last_error: str | None
    created_at: datetime


class InputCreateResponse(InputResponse):
    upserted_existing: bool


class ManualInputSyncResponse(BaseModel):
    input_id: int
    changes_created: int
    email_sent: bool
    last_error: str | None
    is_baseline_sync: bool
    notification_state: str | None = None


class DeadlineItemResponse(BaseModel):
    uid: str
    title: str
    ddl_type: str
    start_at_utc: datetime
    end_at_utc: datetime


class CourseDeadlinesResponse(BaseModel):
    course_label: str
    deadlines: list[DeadlineItemResponse]


class InputDeadlinesPreviewResponse(BaseModel):
    input_id: int
    input_label: str | None
    fetched_at_utc: datetime
    total_deadlines: int
    courses: list[CourseDeadlinesResponse]


class InputRunResponse(BaseModel):
    id: int
    input_id: int
    trigger_type: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    changes_count: int
    error_code: str | None
    error_message: str | None
    duration_ms: int | None
    lock_owner: str | None


class InputCourseOverrideResponse(BaseModel):
    id: int
    input_id: int
    original_course_label: str
    display_course_label: str
    created_at: datetime
    updated_at: datetime


class InputTaskOverrideResponse(BaseModel):
    id: int
    input_id: int
    event_uid: str
    display_title: str
    created_at: datetime
    updated_at: datetime


class InputOverridesResponse(BaseModel):
    input_id: int
    courses: list[InputCourseOverrideResponse]
    tasks: list[InputTaskOverrideResponse]


class EvidencePreviewEvent(BaseModel):
    uid: str | None
    summary: str | None
    dtstart: str | None
    dtend: str | None
    location: str | None
    description: str | None


class EvidencePreviewResponse(BaseModel):
    side: Literal["before", "after"]
    content_type: str
    truncated: bool
    filename: str
    event_count: int
    events: list[EvidencePreviewEvent]
