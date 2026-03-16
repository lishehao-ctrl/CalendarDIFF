from __future__ import annotations

import re
from typing import Any

_ASSIGNMENT_OR_EXAM_MARKERS = (
    "assignment",
    "homework",
    "hw",
    "project",
    "paper",
    "report",
    "problem set",
    "pset",
    "quiz",
    "exam",
    "midterm",
    "final exam",
    "final",
    "deadline",
    "due date",
)
_SESSION_ONLY_MARKERS = (
    "lab",
    "discussion",
    "section",
)


def is_monitored_assignment_or_exam_event(
    *,
    semantic_draft: dict[str, Any] | None,
    source_facts: dict[str, Any] | None,
    kind_resolution: dict[str, Any] | None = None,
) -> bool:
    text = _scope_text(
        values=(
            _string_value(semantic_draft, "raw_type"),
            _string_value(semantic_draft, "event_name"),
            _string_value(source_facts, "source_title"),
            _string_value(source_facts, "source_summary"),
            _string_value(kind_resolution, "canonical_label"),
            _string_value(kind_resolution, "raw_type"),
        )
    )
    if not text:
        return False
    if _has_any_marker(text, _ASSIGNMENT_OR_EXAM_MARKERS):
        return True
    if _has_any_marker(text, _SESSION_ONLY_MARKERS):
        return False
    return False


def is_monitored_assignment_or_exam_directive(
    *,
    selector: dict[str, Any] | None,
    source_facts: dict[str, Any] | None,
) -> bool:
    text = _scope_text(
        values=(
            _string_value(selector, "family_hint"),
            _string_value(selector, "raw_type_hint"),
            _string_value(source_facts, "source_title"),
            _string_value(source_facts, "source_summary"),
        )
    )
    if not text:
        return False
    if _has_any_marker(text, _ASSIGNMENT_OR_EXAM_MARKERS):
        return True
    if _has_any_marker(text, _SESSION_ONLY_MARKERS):
        return False
    return False


def _scope_text(*, values: tuple[str | None, ...]) -> str:
    return " ".join(value.strip().lower() for value in values if isinstance(value, str) and value.strip())


def _string_value(payload: dict[str, Any] | None, key: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _has_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    return any(_text_has_marker(text, marker) for marker in markers)


def _text_has_marker(text: str, marker: str) -> bool:
    return re.search(rf"\b{re.escape(marker.lower())}\b", text) is not None


__all__ = [
    "is_monitored_assignment_or_exam_directive",
    "is_monitored_assignment_or_exam_event",
]
