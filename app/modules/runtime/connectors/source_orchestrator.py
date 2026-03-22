from __future__ import annotations

from app.modules.runtime.connectors.calendar_prefilter import route_calendar_component
from app.modules.runtime.connectors.gmail_prefilter import (
    GMAIL_COURSE_TOOL_SENDER_MARKERS,
    GMAIL_LMS_SENDER_MARKERS,
    GMAIL_STRICT_METADATA_KEYWORDS,
    GMAIL_STRONG_SENDER_MARKERS,
    ParseRoute,
    RouteDecision,
    classify_gmail_sender_family,
    route_gmail_message,
)
from app.modules.runtime.connectors.provider_registry import SourceProcessor, route_source_provider

__all__ = [
    "GMAIL_COURSE_TOOL_SENDER_MARKERS",
    "GMAIL_LMS_SENDER_MARKERS",
    "GMAIL_STRICT_METADATA_KEYWORDS",
    "GMAIL_STRONG_SENDER_MARKERS",
    "ParseRoute",
    "RouteDecision",
    "SourceProcessor",
    "classify_gmail_sender_family",
    "route_calendar_component",
    "route_gmail_message",
    "route_source_provider",
]
