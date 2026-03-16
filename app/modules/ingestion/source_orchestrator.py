from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


ParseRoute = Literal["parse", "skip_unknown"]
GmailSenderFamily = Literal["lms", "course_tools", "unknown_sender"]
SourceProcessor = Literal["gmail", "calendar", "unsupported"]

GMAIL_LMS_SENDER_MARKERS = (
    "canvas",
    "instructure",
    "blackboard",
    "brightspace",
    "d2l",
    "moodle",
)
GMAIL_COURSE_TOOL_SENDER_MARKERS = (
    "piazza",
    "gradescope",
    "edstem",
)
GMAIL_STRONG_SENDER_MARKERS = GMAIL_LMS_SENDER_MARKERS + GMAIL_COURSE_TOOL_SENDER_MARKERS
GMAIL_STRICT_METADATA_KEYWORDS = (
    "assignment",
    "homework",
    "hw",
    "quiz",
    "project",
    "paper",
    "report",
    "problem set",
    "pset",
    "exam",
    "midterm",
    "final exam",
    "deadline",
    "due date",
)
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


@dataclass(frozen=True)
class RouteDecision:
    route: ParseRoute
    sender_family: GmailSenderFamily | None = None


def route_source_provider(*, source_provider: str) -> SourceProcessor:
    normalized = (source_provider or "").strip().lower()
    if normalized == "gmail":
        return "gmail"
    if normalized in {"ics", "calendar"}:
        return "calendar"
    return "unsupported"


def classify_gmail_sender_family(*, from_header: str | None) -> GmailSenderFamily:
    haystack = (from_header or "").lower()
    if any(marker in haystack for marker in GMAIL_LMS_SENDER_MARKERS):
        return "lms"
    if any(marker in haystack for marker in GMAIL_COURSE_TOOL_SENDER_MARKERS):
        return "course_tools"
    return "unknown_sender"


def route_gmail_message(
    *,
    from_header: str | None,
    subject: str | None,
    snippet: str | None,
    body_text: str | None,
    explicit_sender_signal: bool = False,
    explicit_subject_signal: bool = False,
    known_course_tokens: set[str] | None = None,
) -> RouteDecision:
    sender_family = classify_gmail_sender_family(from_header=from_header)
    combined_text = " ".join(part for part in (subject, snippet, body_text) if isinstance(part, str) and part).lower()
    sender_signal = explicit_sender_signal or sender_family in {"lms", "course_tools"}
    keyword_signal = explicit_subject_signal or _text_has_any_keyword_phrase(
        combined_text,
        GMAIL_STRICT_METADATA_KEYWORDS,
    )
    course_signal = any(token in combined_text for token in (known_course_tokens or set()))

    if course_signal or sender_signal or keyword_signal:
        return RouteDecision(route="parse", sender_family=sender_family)
    return RouteDecision(route="skip_unknown", sender_family=sender_family)


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
    "GMAIL_COURSE_TOOL_SENDER_MARKERS",
    "GMAIL_LMS_SENDER_MARKERS",
    "GMAIL_STRICT_METADATA_KEYWORDS",
    "GMAIL_STRONG_SENDER_MARKERS",
    "ParseRoute",
    "RouteDecision",
    "classify_gmail_sender_family",
    "route_calendar_component",
    "route_gmail_message",
    "route_source_provider",
]
