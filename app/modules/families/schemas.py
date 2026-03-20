from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.common.course_identity_schemas import CourseIdentityFields, CourseIdentityResponse


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


class CourseWorkItemFamilyUpdateRequest(BaseModel):
    canonical_label: str = Field(min_length=1, max_length=128)
    raw_types: list[str] = Field(default_factory=list, max_length=64)

    model_config = {"extra": "forbid"}


class CourseWorkItemFamilyStatusResponse(BaseModel):
    state: str
    last_rebuilt_at: datetime | None
    last_error: str | None


class CourseWorkItemFamilyCoursesResponse(BaseModel):
    courses: list[CourseIdentityResponse]


class RawTypeSuggestionItemResponse(BaseModel):
    id: int
    course_display: str
    course_dept: str
    course_number: int
    course_suffix: str | None = None
    course_quarter: str | None = None
    course_year2: int | None = None
    status: Literal["pending", "approved", "rejected", "dismissed"]
    confidence: float
    evidence: str | None = None
    source_observation_id: int | None = None
    source_raw_type: str | None = None
    source_raw_type_id: int | None = None
    source_family_id: int | None = None
    source_family_name: str | None = None
    suggested_raw_type: str | None = None
    suggested_raw_type_id: int | None = None
    suggested_family_id: int | None = None
    suggested_family_name: str | None = None
    review_note: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RawTypeSuggestionDecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "dismiss"]
    note: str | None = Field(default=None, max_length=512)

    model_config = {"extra": "forbid"}


class RawTypeSuggestionDecisionResponse(BaseModel):
    id: int
    status: Literal["pending", "approved", "rejected", "dismissed"]
    review_note: str | None = None
    reviewed_at: datetime | None = None


__all__ = [
    "CourseRawTypeMoveRequest",
    "CourseRawTypeMoveResponse",
    "CourseRawTypeResponse",
    "CourseWorkItemFamilyCoursesResponse",
    "CourseWorkItemFamilyCreateRequest",
    "CourseWorkItemFamilyResponse",
    "CourseWorkItemFamilyStatusResponse",
    "CourseWorkItemFamilyUpdateRequest",
    "RawTypeSuggestionDecisionRequest",
    "RawTypeSuggestionDecisionResponse",
    "RawTypeSuggestionItemResponse",
]
