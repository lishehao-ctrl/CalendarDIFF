from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class SourceCreateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    url: HttpUrl
    interval_minutes: int | None = Field(default=None, ge=1, le=1440)


class SourceResponse(BaseModel):
    id: int
    user_id: int
    type: str
    name: str | None
    interval_minutes: int
    is_active: bool
    last_checked_at: datetime | None
    last_error: str | None
    created_at: datetime


class ManualSyncResponse(BaseModel):
    source_id: int
    changes_created: int
    email_sent: bool
    last_error: str | None


class DeadlineItemResponse(BaseModel):
    uid: str
    title: str
    ddl_type: str
    start_at_utc: datetime
    end_at_utc: datetime


class CourseDeadlinesResponse(BaseModel):
    course_label: str
    deadlines: list[DeadlineItemResponse]


class SourceDeadlinesPreviewResponse(BaseModel):
    source_id: int
    source_name: str | None
    fetched_at_utc: datetime
    total_deadlines: int
    courses: list[CourseDeadlinesResponse]
