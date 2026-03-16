from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.common.payload_schemas import LinkSignals, SemanticEventDraft


SegmentTypeHint = Literal["atomic", "directive", "unknown"]
AtomicExtractionOutcome = Literal["event", "unknown"]
DirectiveExtractionOutcome = Literal["directive", "unknown"]
CalendarExtractionOutcome = Literal["event", "unknown"]
CalendarRelevanceOutcome = Literal["relevant", "unknown"]
GmailPurposeMode = Literal["unknown", "atomic", "directive"]
DirectiveScopeMode = Literal["all_matching", "ordinal_list", "ordinal_range"]
DirectiveWeekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class GmailSourceContextResponse(BaseModel):
    message_id: str | None = Field(default=None, max_length=255)
    source_title: str = Field(default="Untitled", max_length=512)
    source_summary: str | None = Field(default=None, max_length=1024)
    focus_text: str | None = Field(default=None, max_length=4000)
    from_header: str | None = Field(default=None, max_length=512)
    thread_id: str | None = Field(default=None, max_length=255)
    internal_date: str | None = Field(default=None, max_length=64)

    model_config = {"extra": "forbid"}

    @field_validator("message_id", "source_title", "source_summary", "focus_text", "from_header", "thread_id", "internal_date", mode="before")
    @classmethod
    def _strip_context_text(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @model_validator(mode="after")
    def _normalize_title(self):
        if not isinstance(self.source_title, str) or not self.source_title.strip():
            self.source_title = "Untitled"
        return self


class CalendarSourceContextResponse(BaseModel):
    external_event_id: str = Field(min_length=1, max_length=255)
    component_key: str | None = Field(default=None, max_length=255)
    source_title: str = Field(default="Untitled", max_length=512)
    source_summary: str | None = Field(default=None, max_length=1024)
    location: str | None = Field(default=None, max_length=255)
    organizer: str | None = Field(default=None, max_length=255)
    source_dtstart_utc: str | None = Field(default=None, max_length=64)
    source_dtend_utc: str | None = Field(default=None, max_length=64)

    model_config = {"extra": "forbid"}

    @field_validator(
        "external_event_id",
        "component_key",
        "source_title",
        "source_summary",
        "location",
        "organizer",
        "source_dtstart_utc",
        "source_dtend_utc",
        mode="before",
    )
    @classmethod
    def _strip_calendar_context_text(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @model_validator(mode="after")
    def _normalize_calendar_title(self):
        if not isinstance(self.source_title, str) or not self.source_title.strip():
            self.source_title = "Untitled"
        return self


class GmailPurposeModeResponse(BaseModel):
    mode: GmailPurposeMode = "unknown"
    evidence: str = Field(default="", max_length=255)

    model_config = {"extra": "forbid"}

    @field_validator("evidence", mode="before")
    @classmethod
    def _strip_mode_evidence(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()[:255]
        return ""


class CalendarSemanticEventClassification(BaseModel):
    course_dept: str | None = Field(default=None, max_length=16)
    course_number: int | None = Field(default=None, ge=0, le=9999)
    course_suffix: str | None = Field(default=None, max_length=8)
    course_quarter: Literal["WI", "SP", "SU", "FA"] | None = None
    course_year2: int | None = Field(default=None, ge=0, le=99)
    raw_type: str | None = Field(default=None, max_length=128)
    event_name: str | None = Field(default=None, max_length=512)
    ordinal: int | None = Field(default=None, ge=1, le=999)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str = Field(default="", max_length=160)

    model_config = {"extra": "forbid"}

    @field_validator("course_dept", "course_suffix", "raw_type", "event_name", mode="before")
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

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

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: object) -> object:
        if isinstance(value, (int, float)):
            return float(value)
        return 0.0

    @field_validator("evidence", mode="before")
    @classmethod
    def _normalize_evidence(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()[:160]
        return ""


class CalendarRelevanceResponse(BaseModel):
    outcome: CalendarRelevanceOutcome = "unknown"

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_outcome(self):
        return self


class GmailExtractedMessage(BaseModel):
    message_id: str | None = Field(default=None, max_length=255)
    semantic_event_draft: SemanticEventDraft
    link_signals: LinkSignals

    model_config = {"extra": "forbid"}

    @field_validator("message_id", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


class GmailParserResponse(BaseModel):
    messages: list[GmailExtractedMessage] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class GmailPlannerSegment(BaseModel):
    segment_index: int = Field(ge=0)
    anchor: str | None = Field(default=None, max_length=255)
    snippet: str | None = Field(default=None, max_length=2048)
    segment_type_hint: SegmentTypeHint = "unknown"

    model_config = {"extra": "forbid"}

    @field_validator("anchor", "snippet", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


class GmailPlannerResponse(BaseModel):
    message_id: str | None = Field(default=None, max_length=255)
    mode: str = Field(default="single_segment", max_length=64)
    segment_array: list[GmailPlannerSegment] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    @field_validator("message_id", "mode", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
        return value


class GmailAtomicSegmentExtractionResponse(BaseModel):
    outcome: AtomicExtractionOutcome = "event"
    semantic_event_draft: SemanticEventDraft | None = None
    link_signals: LinkSignals | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_outcome(self):
        if self.outcome == "event":
            if self.semantic_event_draft is None or self.link_signals is None:
                raise ValueError("event outcome requires semantic_event_draft and link_signals")
        else:
            self.semantic_event_draft = None
            self.link_signals = None
        return self


class GmailDirectiveSelector(BaseModel):
    course_dept: str | None = Field(default=None, max_length=16)
    course_number: int | None = Field(default=None, ge=0, le=9999)
    course_suffix: str | None = Field(default=None, max_length=8)
    course_quarter: Literal["WI", "SP", "SU", "FA"] | None = None
    course_year2: int | None = Field(default=None, ge=0, le=99)
    family_hint: str | None = Field(default=None, max_length=128)
    raw_type_hint: str | None = Field(default=None, max_length=128)
    scope_mode: DirectiveScopeMode = "all_matching"
    ordinal_list: list[int] = Field(default_factory=list)
    ordinal_range_start: int | None = Field(default=None, ge=1, le=999)
    ordinal_range_end: int | None = Field(default=None, ge=1, le=999)
    current_due_weekday: DirectiveWeekday | None = None
    applies_to_future_only: bool = False

    model_config = {"extra": "forbid"}

    @field_validator("course_dept", "course_suffix", "family_hint", "raw_type_hint", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @model_validator(mode="after")
    def _validate_scope(self):
        if self.scope_mode == "ordinal_list" and not self.ordinal_list:
            raise ValueError("ordinal_list scope requires non-empty ordinal_list")
        if self.scope_mode == "ordinal_range":
            if self.ordinal_range_start is None or self.ordinal_range_end is None:
                raise ValueError("ordinal_range scope requires ordinal_range_start and ordinal_range_end")
            if self.ordinal_range_start > self.ordinal_range_end:
                raise ValueError("ordinal_range_start must be <= ordinal_range_end")
        return self


class GmailDirectiveMutation(BaseModel):
    move_weekday: DirectiveWeekday | None = None
    set_due_date: date | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_exactly_one(self):
        present = int(self.move_weekday is not None) + int(self.set_due_date is not None)
        if present != 1:
            raise ValueError("directive mutation requires exactly one of move_weekday or set_due_date")
        return self


class GmailDirectiveExtractionResponse(BaseModel):
    outcome: DirectiveExtractionOutcome = "directive"
    selector: GmailDirectiveSelector | None = None
    mutation: GmailDirectiveMutation | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str = Field(default="", max_length=255)

    model_config = {"extra": "forbid"}

    @field_validator("evidence", mode="before")
    @classmethod
    def _strip_evidence(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()[:255]
        return ""

    @model_validator(mode="after")
    def _validate_outcome(self):
        if self.outcome == "directive":
            if self.selector is None or self.mutation is None:
                raise ValueError("directive outcome requires selector and mutation")
        else:
            self.selector = None
            self.mutation = None
            self.confidence = 0.0
            self.evidence = ""
        return self


__all__ = [
    "CalendarSourceContextResponse",
    "CalendarRelevanceResponse",
    "GmailAtomicSegmentExtractionResponse",
    "GmailDirectiveExtractionResponse",
    "GmailDirectiveMutation",
    "GmailDirectiveSelector",
    "GmailExtractedMessage",
    "GmailPlannerResponse",
    "GmailPlannerSegment",
    "GmailParserResponse",
    "GmailPurposeMode",
    "GmailPurposeModeResponse",
    "GmailSourceContextResponse",
    "DirectiveScopeMode",
    "DirectiveWeekday",
    "SegmentTypeHint",
]
