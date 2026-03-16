from __future__ import annotations

from datetime import date, datetime, time
from email.utils import parseaddr
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from app.modules.common.event_display import UserFacingEventResponse
from app.modules.common.course_identity import normalize_course_identity

class UserResponse(BaseModel):
    id: int
    email: str | None
    notify_email: str | None
    timezone_name: str
    timezone_source: str
    calendar_delay_seconds: int
    created_at: datetime


class UserUpdateRequest(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    notify_email: str | None = Field(default=None, max_length=255)
    timezone_name: str | None = Field(default=None, max_length=64)
    timezone_source: str | None = Field(default=None, max_length=16)
    calendar_delay_seconds: int | None = Field(default=None, ge=0, le=3600)

    model_config = {"extra": "forbid"}

    @field_validator("email", "notify_email")
    @classmethod
    def validate_optional_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        if not _is_valid_email_address(stripped):
            raise ValueError("must be a valid email address")
        return stripped

    @field_validator("timezone_name")
    @classmethod
    def validate_timezone_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_timezone_name(value)

    @field_validator("timezone_source")
    @classmethod
    def validate_timezone_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip().lower()
        if stripped not in {"auto", "manual"}:
            raise ValueError("timezone_source must be either 'auto' or 'manual'")
        return stripped


class CourseIdentityFields(BaseModel):
    course_dept: str = Field(min_length=1, max_length=16)
    course_number: int = Field(ge=0, le=9999)
    course_suffix: str | None = Field(default=None, max_length=8)
    course_quarter: str | None = Field(default=None, max_length=4)
    course_year2: int | None = Field(default=None, ge=0, le=99)

    model_config = {"extra": "forbid"}

    @field_validator("course_dept", "course_suffix", "course_quarter", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip().upper()
            return cleaned or None
        return value

    @field_validator("course_dept")
    @classmethod
    def _validate_dept(cls, value: str) -> str:
        normalized = normalize_course_identity(course_dept=value, course_number=1)["course_dept"]
        if not isinstance(normalized, str):
            raise ValueError("course_dept must not be blank")
        return normalized


class CourseIdentityResponse(BaseModel):
    course_display: str
    course_dept: str
    course_number: int
    course_suffix: str | None = None
    course_quarter: str | None = None
    course_year2: int | None = None


class CourseWorkItemFamilyResponse(CourseIdentityResponse):
    id: int
    canonical_label: str
    raw_types: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CourseRawTypeResponse(CourseIdentityResponse):
    id: int
    family_id: int
    raw_type: str
    created_at: datetime
    updated_at: datetime


class CourseRawTypeMoveRequest(BaseModel):
    raw_type_id: int = Field(ge=1)
    family_id: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}


class CourseRawTypeMoveResponse(CourseIdentityResponse):
    raw_type_id: int
    family_id: int
    previous_family_id: int


class CourseWorkItemFamilyCreateRequest(CourseIdentityFields):
    canonical_label: str = Field(min_length=1, max_length=128)
    raw_types: list[str] = Field(default_factory=list, max_length=64)


class CourseWorkItemFamilyUpdateRequest(CourseIdentityFields):
    canonical_label: str = Field(min_length=1, max_length=128)
    raw_types: list[str] = Field(default_factory=list, max_length=64)


class CourseWorkItemFamilyStatusResponse(BaseModel):
    state: str
    last_rebuilt_at: datetime | None
    last_error: str | None


class CourseWorkItemFamilyCoursesResponse(BaseModel):
    courses: list[CourseIdentityResponse]


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


def _is_valid_email_address(value: str | None) -> bool:
    if value is None:
        return False
    candidate = value.strip()
    if not candidate:
        return False
    if any(ch.isspace() for ch in candidate):
        return False
    _, parsed = parseaddr(candidate)
    if parsed != candidate:
        return False
    local, separator, domain = candidate.rpartition("@")
    if separator != "@":
        return False
    if not local or not domain or "." not in domain:
        return False
    if domain.startswith(".") or domain.endswith(".") or ".." in domain:
        return False
    return True


def _normalize_timezone_name(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("timezone_name must not be blank")
    try:
        ZoneInfo(stripped)
    except Exception as exc:
        raise ValueError("timezone_name must be a valid IANA timezone") from exc
    return stripped
