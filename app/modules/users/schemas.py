from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.users.email_utils import is_valid_email_address


class UserResponse(BaseModel):
    id: int
    email: str | None
    notify_email: str | None
    timezone_name: str
    calendar_delay_seconds: int
    created_at: datetime


class UserUpdateRequest(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    notify_email: str | None = Field(default=None, max_length=255)
    timezone_name: str | None = Field(default=None, max_length=64)
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
        if not is_valid_email_address(stripped):
            raise ValueError("must be a valid email address")
        return stripped

    @field_validator("timezone_name")
    @classmethod
    def validate_timezone_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("timezone_name must not be blank")
        return stripped

class CourseWorkItemFamilyResponse(BaseModel):
    id: int
    course_key: str
    canonical_label: str
    aliases: list[str]
    created_at: datetime
    updated_at: datetime


class CourseWorkItemFamilyCreateRequest(BaseModel):
    course_key: str = Field(min_length=1, max_length=128)
    canonical_label: str = Field(min_length=1, max_length=128)
    aliases: list[str] = Field(default_factory=list, max_length=64)

    model_config = {"extra": "forbid"}


class CourseWorkItemFamilyUpdateRequest(BaseModel):
    course_key: str = Field(min_length=1, max_length=128)
    canonical_label: str = Field(min_length=1, max_length=128)
    aliases: list[str] = Field(default_factory=list, max_length=64)

    model_config = {"extra": "forbid"}


class CourseWorkItemFamilyStatusResponse(BaseModel):
    state: str
    last_rebuilt_at: datetime | None
    last_error: str | None


class CourseWorkItemFamilyCoursesResponse(BaseModel):
    courses: list[str]
