from __future__ import annotations

from collections.abc import Sequence

from app.db.models.review import Event, SourceEventObservation
from app.modules.core_ingest.canonical_coercion import parse_iso_datetime
from app.modules.core_ingest.entity_profile import course_display_name
from app.modules.core_ingest.payload_extractors import extract_enrichment_course_parse
from app.modules.core_ingest.time_utils import as_utc


def serialize_proposal_sources(observations: Sequence[SourceEventObservation]) -> list[dict]:
    rows: list[dict] = []
    for row in observations:
        payload = row.event_payload if isinstance(row.event_payload, dict) else {}
        confidence_raw = payload.get("confidence")
        confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.0
        rows.append(
            {
                "source_id": row.source_id,
                "source_kind": row.source_kind.value,
                "provider": row.provider,
                "external_event_id": row.external_event_id,
                "confidence": confidence,
            }
        )
    rows.sort(
        key=lambda item: (
            float(item.get("confidence") or 0.0),
            2 if item.get("source_kind") == "calendar" else 1 if item.get("source_kind") == "email" else 0,
        ),
        reverse=True,
    )
    return rows


def candidate_after_json(*, merge_key: str, payload: dict) -> dict | None:
    source_canonical_raw = payload.get("source_canonical")
    source_canonical = source_canonical_raw if isinstance(source_canonical_raw, dict) else {}
    start_raw = source_canonical.get("source_dtstart_utc")
    end_raw = source_canonical.get("source_dtend_utc")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        return None
    start_at = parse_iso_datetime(start_raw, field="start_at_utc", uid=merge_key)
    end_at = parse_iso_datetime(end_raw, field="end_at_utc", uid=merge_key)
    if end_at <= start_at:
        return None

    title_raw = source_canonical.get("source_title")
    title = title_raw if isinstance(title_raw, str) else None
    course_label = payload.get("course_label") if isinstance(payload.get("course_label"), str) else None
    if not course_label:
        course_label = course_display_name(course_parse=extract_enrichment_course_parse(payload=payload)) or "Unknown"
    return {
        "uid": merge_key,
        "title": (title or "Untitled")[:512],
        "course_label": (course_label or "Unknown")[:64],
        "start_at_utc": start_at.isoformat(),
        "end_at_utc": end_at.isoformat(),
    }


def event_row_to_json(event: Event) -> dict:
    return {
        "uid": event.uid,
        "title": event.title,
        "course_label": event.course_label,
        "start_at_utc": as_utc(event.start_at_utc).isoformat(),
        "end_at_utc": as_utc(event.end_at_utc).isoformat(),
    }


def event_json_equivalent(before_json: dict, after_json: dict) -> bool:
    return (
        str(before_json.get("title") or "") == str(after_json.get("title") or "")
        and str(before_json.get("start_at_utc") or "") == str(after_json.get("start_at_utc") or "")
        and str(before_json.get("end_at_utc") or "") == str(after_json.get("end_at_utc") or "")
    )


def safe_delta_seconds(*, before_json: dict, after_json: dict) -> int | None:
    before_raw = before_json.get("start_at_utc")
    after_raw = after_json.get("start_at_utc")
    if not isinstance(before_raw, str) or not isinstance(after_raw, str):
        return None
    before = parse_iso_datetime(before_raw, field="start_at_utc", uid="before")
    after = parse_iso_datetime(after_raw, field="start_at_utc", uid="after")
    return int((after - before).total_seconds())


__all__ = [
    "candidate_after_json",
    "event_json_equivalent",
    "event_row_to_json",
    "safe_delta_seconds",
    "serialize_proposal_sources",
]
