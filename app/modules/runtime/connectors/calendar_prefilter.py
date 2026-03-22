from __future__ import annotations

import re

from app.modules.runtime.connectors.gmail_prefilter import RouteDecision


_CALENDAR_WORK_TEST_HINTS = (
    "assignment",
    "homework",
    "hw",
    "quiz",
    "exam",
    "midterm",
    "final",
    "project",
    "paper",
    "report",
    "reflection",
    "problem set",
    "pset",
    "rq",
    "programming assignment",
)


def route_calendar_component(
    *,
    source_title: str | None,
    source_summary: str | None,
) -> RouteDecision:
    combined_text = " ".join(part for part in (source_title, source_summary) if isinstance(part, str) and part).lower()
    if _text_has_any_keyword_phrase(combined_text, _CALENDAR_WORK_TEST_HINTS):
        return RouteDecision(route="parse")
    return RouteDecision(route="skip_unknown")


def _text_has_any_keyword_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(_text_has_phrase(text, phrase) for phrase in phrases)


def _text_has_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase.lower())}\b", text) is not None


__all__ = [
    "route_calendar_component",
]
