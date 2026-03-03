from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime, timezone

from icalendar import Calendar

from app.modules.ingestion.ics_delta.fingerprint import (
    build_component_key,
    build_external_event_id,
    compute_component_fingerprint,
)


class IcsDeltaParseError(RuntimeError):
    """Raised when ICS content cannot be parsed into a VEVENT snapshot."""


@dataclass(frozen=True)
class ParsedIcsComponent:
    component_key: str
    external_event_id: str
    fingerprint: str
    component_ical_b64: str


@dataclass(frozen=True)
class ParsedIcsSnapshot:
    components: dict[str, ParsedIcsComponent]
    cancelled_component_keys: set[str]
    total_components: int
    invalid_components: int


def parse_ics_snapshot(*, content: bytes) -> ParsedIcsSnapshot:
    if not content:
        raise IcsDeltaParseError("ics content is empty")
    try:
        calendar = Calendar.from_ical(content)
    except Exception as exc:
        raise IcsDeltaParseError(f"ics parse failed: {exc}") from exc

    components: dict[str, ParsedIcsComponent] = {}
    cancelled_component_keys: set[str] = set()
    total_components = 0
    invalid_components = 0

    for component in calendar.walk():
        if getattr(component, "name", "") != "VEVENT":
            continue
        total_components += 1

        uid = _normalize_text(component.get("UID"))
        if not uid:
            invalid_components += 1
            continue

        recurrence_id = _normalize_ical_value(component.get("RECURRENCE-ID"))
        component_key = build_component_key(uid=uid, recurrence_id=recurrence_id)
        external_event_id = build_external_event_id(uid=uid, recurrence_id=recurrence_id)
        status = (_normalize_text(component.get("STATUS")) or "").upper()
        fingerprint = compute_component_fingerprint(
            fields={
                "UID": uid,
                "RECURRENCE-ID": recurrence_id,
                "DTSTART": _normalize_ical_value(component.get("DTSTART")),
                "DTEND": _normalize_ical_value(component.get("DTEND")),
                "DUE": _normalize_ical_value(component.get("DUE")),
                "SUMMARY": _normalize_text(component.get("SUMMARY")),
                "DESCRIPTION": _normalize_text(component.get("DESCRIPTION")),
                "LOCATION": _normalize_text(component.get("LOCATION")),
                "STATUS": status or None,
                "SEQUENCE": _normalize_sequence(component.get("SEQUENCE")),
                "LAST-MODIFIED": _normalize_ical_value(component.get("LAST-MODIFIED")),
            }
        )
        component_ical_b64 = base64.b64encode(component.to_ical()).decode("ascii")

        if status == "CANCELLED":
            cancelled_component_keys.add(component_key)
            continue

        components[component_key] = ParsedIcsComponent(
            component_key=component_key,
            external_event_id=external_event_id,
            fingerprint=fingerprint,
            component_ical_b64=component_ical_b64,
        )

    return ParsedIcsSnapshot(
        components=components,
        cancelled_component_keys=cancelled_component_keys,
        total_components=total_components,
        invalid_components=invalid_components,
    )


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _normalize_sequence(value: object) -> int | None:
    if value is None:
        return None
    candidate = value
    if hasattr(candidate, "dt"):
        candidate = candidate.dt
    try:
        return int(candidate)
    except Exception:
        text = str(candidate).strip()
        if not text:
            return None
        try:
            return int(text)
        except Exception:
            return None


def _normalize_ical_value(value: object) -> str | None:
    if value is None:
        return None
    candidate = value
    if hasattr(candidate, "dt"):
        candidate = candidate.dt

    if isinstance(candidate, datetime):
        if candidate.tzinfo is None:
            return candidate.isoformat()
        return candidate.astimezone(timezone.utc).isoformat()
    if isinstance(candidate, date):
        return candidate.isoformat()

    text = str(candidate).strip()
    if not text:
        return None
    return text
