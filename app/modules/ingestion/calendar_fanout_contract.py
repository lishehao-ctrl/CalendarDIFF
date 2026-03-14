from __future__ import annotations

CALENDAR_COMPONENT_REASON_PREFIX = "calendar_component:"
CALENDAR_REDUCE_REASON = "calendar_reduce"


def build_calendar_component_reason(component_key: str) -> str:
    return f"{CALENDAR_COMPONENT_REASON_PREFIX}{component_key}"


def parse_component_key_from_reason(reason: str) -> str | None:
    if not isinstance(reason, str):
        return None
    if not reason.startswith(CALENDAR_COMPONENT_REASON_PREFIX):
        return None
    key = reason[len(CALENDAR_COMPONENT_REASON_PREFIX) :].strip()
    return key or None


def is_calendar_component_reason(reason: str) -> bool:
    return parse_component_key_from_reason(reason) is not None


def is_calendar_reduce_reason(reason: str) -> bool:
    return isinstance(reason, str) and reason.strip() == CALENDAR_REDUCE_REASON


def is_calendar_fanout_reason(reason: str) -> bool:
    return is_calendar_component_reason(reason) or is_calendar_reduce_reason(reason)


__all__ = [
    "CALENDAR_COMPONENT_REASON_PREFIX",
    "CALENDAR_REDUCE_REASON",
    "build_calendar_component_reason",
    "is_calendar_component_reason",
    "is_calendar_fanout_reason",
    "is_calendar_reduce_reason",
    "parse_component_key_from_reason",
]
