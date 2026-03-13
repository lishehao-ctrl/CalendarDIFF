from __future__ import annotations

from datetime import datetime

from app.modules.common.course_identity import course_display_name
from app.modules.common.payload_schemas import SourceFacts
from app.modules.core_ingest.time_utils import as_utc
from app.modules.sync.types import CanonicalEventInput


def coerce_calendar_payload(*, payload: dict) -> CanonicalEventInput:
    from app.modules.core_ingest.payload_extractors import extract_enrichment_course_parse

    source_facts_raw = payload.get("source_facts")
    try:
        source_facts = SourceFacts.model_validate(source_facts_raw if isinstance(source_facts_raw, dict) else {})
    except Exception as exc:
        raise RuntimeError("core_ingest_payload_invalid: calendar payload missing source_facts.external_event_id") from exc
    uid = source_facts.external_event_id
    if not uid:
        raise RuntimeError("core_ingest_payload_invalid: calendar payload missing source_facts.external_event_id")

    title_raw = source_facts.source_title
    if not isinstance(title_raw, str) or not title_raw.strip():
        raise RuntimeError(f"calendar record uid={uid} missing non-empty source_facts.source_title")
    title = title_raw.strip()

    course_label = course_display_name(course_parse=extract_enrichment_course_parse(payload=payload)) or "Unknown"

    start_value = source_facts.source_dtstart_utc
    end_value = source_facts.source_dtend_utc
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
