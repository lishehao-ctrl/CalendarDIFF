from __future__ import annotations

from datetime import datetime

from app.modules.core_ingest.time_utils import as_utc
from app.modules.sync.types import CanonicalEventInput


def coerce_calendar_payload(*, payload: dict) -> CanonicalEventInput:
    from app.modules.core_ingest.entity_profile import course_display_name
    from app.modules.core_ingest.payload_extractors import extract_enrichment_course_parse

    source_canonical_raw = payload.get("source_canonical")
    source_canonical = source_canonical_raw if isinstance(source_canonical_raw, dict) else {}
    uid_raw = source_canonical.get("external_event_id")
    uid = uid_raw.strip() if isinstance(uid_raw, str) and uid_raw.strip() else ""
    if not uid:
        raise RuntimeError("core_ingest_payload_invalid: calendar payload missing source_canonical.external_event_id")

    title_raw = source_canonical.get("source_title")
    if not isinstance(title_raw, str) or not title_raw.strip():
        raise RuntimeError(f"calendar record uid={uid} missing non-empty source_canonical.source_title")
    title = title_raw.strip()

    course_label = course_display_name(course_parse=extract_enrichment_course_parse(payload=payload)) or "Unknown"

    start_value = source_canonical.get("source_dtstart_utc")
    end_value = source_canonical.get("source_dtend_utc")
    start_at = parse_iso_datetime(start_value, field="start_at", uid=uid)
    end_at = parse_iso_datetime(end_value, field="end_at", uid=uid)
    if end_at <= start_at:
        raise RuntimeError(f"calendar record uid={uid} has end_at <= start_at")

    return CanonicalEventInput(
        uid=uid,
        course_label=course_label[:64],
        title=title[:512],
        start_at_utc=start_at,
        end_at_utc=end_at,
    )


def parse_iso_datetime(value: object, *, field: str, uid: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"calendar record uid={uid} missing {field}")
    raw = value.strip()
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise RuntimeError(f"calendar record uid={uid} has invalid {field}: {raw}") from exc
    return as_utc(parsed)


def parse_optional_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return as_utc(parsed)


def coerce_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


__all__ = [
    "coerce_calendar_payload",
    "coerce_text",
    "parse_iso_datetime",
    "parse_optional_iso_datetime",
]
