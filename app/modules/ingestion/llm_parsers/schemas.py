from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.common.payload_schemas import LinkSignals, SemanticEventDraft


class SemanticEventDraftResponse(BaseModel):
    semantic_event_draft: SemanticEventDraft
    link_signals: LinkSignals

    model_config = {"extra": "forbid"}


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


SegmentTypeHint = Literal["atomic", "directive", "unknown"]
DirectiveScopeMode = Literal["all_matching", "ordinal_list", "ordinal_range"]
DirectiveWeekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


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
    semantic_event_draft: SemanticEventDraft
    link_signals: LinkSignals

    model_config = {"extra": "forbid"}


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
    selector: GmailDirectiveSelector
    mutation: GmailDirectiveMutation
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str = Field(default="", max_length=255)

    model_config = {"extra": "forbid"}

    @field_validator("evidence", mode="before")
    @classmethod
    def _strip_evidence(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()[:255]
        return ""


__all__ = [
    "GmailAtomicSegmentExtractionResponse",
    "GmailDirectiveExtractionResponse",
    "GmailDirectiveMutation",
    "GmailDirectiveSelector",
    "GmailExtractedMessage",
    "GmailPlannerResponse",
    "GmailPlannerSegment",
    "GmailParserResponse",
    "DirectiveScopeMode",
    "DirectiveWeekday",
    "SegmentTypeHint",
    "SemanticEventDraftResponse",
]
