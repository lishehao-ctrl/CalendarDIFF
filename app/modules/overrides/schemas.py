from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CourseRenameRequest(BaseModel):
    original_course_label: str = Field(..., min_length=1, max_length=64)
    display_course_label: str = Field(..., min_length=1, max_length=64)


class TaskRenameRequest(BaseModel):
    display_title: str = Field(..., min_length=1, max_length=512)


class CourseOverrideResponse(BaseModel):
    id: int
    input_id: int
    original_course_label: str
    display_course_label: str
    created_at: datetime
    updated_at: datetime


class TaskOverrideResponse(BaseModel):
    id: int
    input_id: int
    event_uid: str
    display_title: str
    created_at: datetime
    updated_at: datetime


class InputOverridesResponse(BaseModel):
    input_id: int
    courses: list[CourseOverrideResponse]
    tasks: list[TaskOverrideResponse]
