from __future__ import annotations

from typing import Literal


SourceProcessor = Literal["gmail", "calendar", "unsupported"]


def route_source_provider(*, source_provider: str) -> SourceProcessor:
    normalized = (source_provider or "").strip().lower()
    if normalized == "gmail":
        return "gmail"
    if normalized in {"ics", "calendar"}:
        return "calendar"
    return "unsupported"


__all__ = [
    "SourceProcessor",
    "route_source_provider",
]
