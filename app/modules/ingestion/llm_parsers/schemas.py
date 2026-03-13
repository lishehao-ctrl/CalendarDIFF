from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

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


__all__ = [
    "GmailExtractedMessage",
    "GmailParserResponse",
    "SemanticEventDraftResponse",
]
