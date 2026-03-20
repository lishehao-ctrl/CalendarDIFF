from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.common.event_display import EventDisplayResponse

CourseQuarter = Literal["WI", "SP", "SU", "FA"]
TimePrecision = Literal["date_only", "datetime"]
SourceKindValue = Literal["calendar", "email"]
FrozenStructuredKind = Literal["ics_event", "gmail_event", "generic"]


class StrictSchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SemanticPayloadBase(StrictSchemaModel):
    uid: str | None = Field(default=None, max_length=128)
    family_id: int | None = Field(default=None, ge=1)
    family_name: str | None = Field(default=None, max_length=128)
    course_dept: str | None = Field(default=None, max_length=16)
    course_number: int | None = Field(default=None, ge=0, le=9999)
    course_suffix: str | None = Field(default=None, max_length=8)
    course_quarter: CourseQuarter | None = None
    course_year2: int | None = Field(default=None, ge=0, le=99)
    raw_type: str | None = Field(default=None, max_length=128)
    event_name: str | None = Field(default=None, max_length=512)
    ordinal: int | None = Field(default=None, ge=1, le=999)
    due_date: date | None = None
    due_time: time | None = None
    time_precision: TimePrecision = "datetime"

    @field_validator("uid", "family_name", "course_dept", "course_suffix", "raw_type", "event_name", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("course_dept", "course_suffix", mode="after")
    @classmethod
    def _normalize_course_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().upper()
        return cleaned or None

    @field_validator("course_quarter", mode="before")
    @classmethod
    def _normalize_quarter(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        cleaned = value.strip().upper()
        return cleaned or None

    @field_validator("time_precision", mode="before")
    @classmethod
    def _normalize_time_precision(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().lower() == "date_only":
            return "date_only"
        return "datetime"

    @field_validator("due_time", mode="before")
    @classmethod
    def _normalize_due_time(cls, value: object) -> object:
        if isinstance(value, time):
            return value.replace(tzinfo=None)
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return None
            parsed = time.fromisoformat(cleaned)
            return parsed.replace(tzinfo=None)
        return None

    @field_validator("due_date", mode="before")
    @classmethod
    def _normalize_due_date(cls, value: object) -> object:
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            cleaned = value.strip()
            return date.fromisoformat(cleaned) if cleaned else None
        return None

    def to_json_dict(self) -> dict:
        payload = self.model_dump(mode="json")
        if payload.get("time_precision") == "date_only":
            payload["due_time"] = None
        return payload


class ApprovedSemanticPayload(SemanticPayloadBase):
    uid: str = Field(max_length=128)


class SemanticEventDraft(SemanticPayloadBase):
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str = Field(default="", max_length=160)

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: object) -> object:
        if isinstance(value, (int, float)):
            return float(value)
        return 0.0

    @field_validator("evidence", mode="before")
    @classmethod
    def _normalize_evidence(cls, value: object) -> object:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()[:160]
        return ""


class LinkSignals(StrictSchemaModel):
    keywords: list[str] = Field(default_factory=list)
    exam_sequence: int | None = Field(default=None, ge=1, le=20)
    location_text: str | None = Field(default=None, max_length=256)
    instructor_hint: str | None = Field(default=None, max_length=255)
    from_header: str | None = Field(default=None, max_length=255)
    organizer: str | None = Field(default=None, max_length=255)
    thread_id: str | None = Field(default=None, max_length=255)
    time_anchor_confidence: float | None = Field(default=None, ge=0.0, le=1.0)

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
            if token not in {"exam", "midterm", "final"} or token in seen:
                continue
            seen.add(token)
            out.append(token)
        return out

    @field_validator("location_text", "instructor_hint", "from_header", "organizer", "thread_id", mode="before")
    @classmethod
    def _normalize_signal_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None


class SourceFacts(StrictSchemaModel):
    external_event_id: str = Field(max_length=255)
    source_title: str = Field(max_length=512)
    source_summary: str | None = Field(default=None, max_length=1024)
    source_dtstart_utc: str | None = Field(default=None, max_length=64)
    source_dtend_utc: str | None = Field(default=None, max_length=64)
    source_time_precision: TimePrecision | None = None
    component_key: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, max_length=64)
    location: str | None = Field(default=None, max_length=512)
    organizer: str | None = Field(default=None, max_length=255)
    from_header: str | None = Field(default=None, max_length=255)
    thread_id: str | None = Field(default=None, max_length=255)
    internal_date: str | None = Field(default=None, max_length=64)
    time_anchor_confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator(
        "external_event_id",
        "source_title",
        "source_summary",
        "source_dtstart_utc",
        "source_dtend_utc",
        "component_key",
        "status",
        "location",
        "organizer",
        "from_header",
        "thread_id",
        "internal_date",
        mode="before",
    )
    @classmethod
    def _normalize_source_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None


class ChangeSourceRefPayload(StrictSchemaModel):
    source_id: int = Field(ge=1)
    source_kind: SourceKindValue | None = None
    provider: str | None = Field(default=None, max_length=64)
    external_event_id: str | None = Field(default=None, max_length=255)
    confidence: float | None = Field(default=None, ge=0.0)

    @field_validator("provider", "external_event_id", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None

    def to_primary_ref(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "provider": self.provider,
            "external_event_id": self.external_event_id,
        }


class FrozenEvidenceEvent(StrictSchemaModel):
    uid: str | None = None
    summary: str | None = None
    dtstart: str | None = None
    dtend: str | None = None
    location: str | None = None
    description: str | None = None
    url: str | None = None


class FrozenEvidenceStructuredItem(StrictSchemaModel):
    uid: str | None = None
    event_display: EventDisplayResponse | None = None
    source_title: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    location: str | None = None
    description: str | None = None
    url: str | None = None
    sender: str | None = None
    snippet: str | None = None
    internal_date: str | None = None
    thread_id: str | None = None


class FrozenChangeEvidence(StrictSchemaModel):
    provider: str | None = Field(default=None, max_length=64)
    content_type: str
    structured_kind: FrozenStructuredKind = "generic"
    structured_items: list[FrozenEvidenceStructuredItem] = Field(default_factory=list)
    event_count: int = Field(default=0, ge=0)
    events: list[FrozenEvidenceEvent] = Field(default_factory=list)
    preview_text: str | None = None


class ChangeSummaryPayloadSide(StrictSchemaModel):
    value_time: datetime | None = None
    source_label: str | None = None
    source_kind: SourceKindValue | None = None
    source_observed_at: datetime | None = None


class ChangeSummaryPayload(StrictSchemaModel):
    old: ChangeSummaryPayloadSide
    new: ChangeSummaryPayloadSide


def model_json_dict(model: BaseModel) -> dict:
    return model.model_dump(mode="json")


__all__ = [
    "ApprovedSemanticPayload",
    "ChangeSourceRefPayload",
    "CourseQuarter",
    "FrozenEvidenceEvent",
    "FrozenEvidenceStructuredItem",
    "FrozenChangeEvidence",
    "FrozenStructuredKind",
    "LinkSignals",
    "ChangeSummaryPayload",
    "ChangeSummaryPayloadSide",
    "SemanticEventDraft",
    "SourceFacts",
    "SourceKindValue",
    "StrictSchemaModel",
    "TimePrecision",
    "model_json_dict",
]
