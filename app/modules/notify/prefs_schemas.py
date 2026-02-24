from __future__ import annotations

import re
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class NotificationPrefsResponse(BaseModel):
    digest_enabled: bool
    timezone: str
    digest_times: list[str]


class NotificationPrefsUpdateRequest(BaseModel):
    digest_enabled: bool | None = None
    timezone: str | None = None
    digest_times: list[str] | None = Field(default=None)

    model_config = {"extra": "forbid"}

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("timezone must not be blank")
        try:
            ZoneInfo(stripped)
        except Exception as exc:  # pragma: no cover - platform-specific tzdata behavior
            raise ValueError("invalid timezone") from exc
        return stripped

    @field_validator("digest_times")
    @classmethod
    def validate_times(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = normalize_digest_times(value)
        if len(normalized) < 1 or len(normalized) > 6:
            raise ValueError("digest_times must contain between 1 and 6 entries")
        return normalized


def normalize_digest_times(raw: list[Any]) -> list[str]:
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        stripped = item.strip()
        if not stripped:
            continue
        if not TIME_PATTERN.match(stripped):
            continue
        values.append(stripped)
    deduped = sorted(set(values))
    return deduped
