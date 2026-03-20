from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.modules.common.course_identity import normalize_course_identity


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


__all__ = [
    "CourseIdentityFields",
    "CourseIdentityResponse",
]
