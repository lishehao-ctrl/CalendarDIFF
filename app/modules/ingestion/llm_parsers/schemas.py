from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CourseParse(BaseModel):
    dept: str | None = Field(default=None, max_length=16)
    number: int | None = Field(default=None, ge=0, le=9999)
    suffix: str | None = Field(default=None, max_length=8)
    quarter: Literal["WI", "SP", "SU", "FA"] | None = None
    year2: int | None = Field(default=None, ge=0, le=99)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str = Field(default="", max_length=80)

    model_config = {"extra": "forbid"}

    @field_validator("dept", "suffix", mode="before")
    @classmethod
    def _normalize_code(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip().upper()
            return cleaned or None
        return None

    @field_validator("quarter", mode="before")
    @classmethod
    def _normalize_quarter(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip().upper()
            return cleaned or None
        return None

    @field_validator("evidence", mode="before")
    @classmethod
    def _normalize_evidence(cls, value: object) -> object:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()[:80]
        return ""


class CourseParseResponse(BaseModel):
    course_parse: CourseParse

    model_config = {"extra": "forbid"}


class LinkSignals(BaseModel):
    keywords: list[Literal["exam", "midterm", "final"]] = Field(default_factory=list)
    exam_sequence: int | None = Field(default=None, ge=1, le=20)
    location_text: str | None = Field(default=None, max_length=256)
    instructor_hint: str | None = Field(default=None, max_length=255)

    model_config = {"extra": "forbid"}

    @field_validator("keywords", mode="before")
    @classmethod
    def _normalize_keywords(cls, value: object) -> object:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                continue
            token = item.strip().lower()
            if token not in {"exam", "midterm", "final"}:
                continue
            if token in seen:
                continue
            seen.add(token)
            out.append(token)
        return out

    @field_validator("location_text", "instructor_hint", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None


class EventParts(BaseModel):
    type: Literal["exam", "deadline", "quiz", "project", "lecture", "other"] | None = None
    index: int | None = Field(default=None, ge=1, le=999)
    qualifier: str | None = Field(default=None, max_length=128)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str = Field(default="", max_length=120)

    model_config = {"extra": "forbid"}

    @field_validator("type", mode="before")
    @classmethod
    def _normalize_type(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip().lower()
            return cleaned or None
        return None

    @field_validator("qualifier", mode="before")
    @classmethod
    def _normalize_qualifier(cls, value: object) -> object:
        if not isinstance(value, str):
            return None
        cleaned = value.strip().lower()
        return cleaned or None

    @field_validator("evidence", mode="before")
    @classmethod
    def _normalize_event_evidence(cls, value: object) -> object:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()[:120]
        return ""


class EventEnrichmentResponse(BaseModel):
    course_parse: CourseParse
    event_parts: EventParts
    link_signals: LinkSignals

    model_config = {"extra": "forbid"}


class GmailExtractedMessage(BaseModel):
    message_id: str | None = Field(default=None, max_length=255)
    due_at: str | None = Field(default=None, max_length=128)
    time_anchor_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    course_parse: CourseParse
    event_parts: EventParts
    link_signals: LinkSignals

    model_config = {"extra": "forbid"}

    @field_validator("message_id", "due_at", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


class GmailParserResponse(BaseModel):
    messages: list[GmailExtractedMessage] = Field(default_factory=list)

    model_config = {"extra": "forbid"}
