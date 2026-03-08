from __future__ import annotations

import base64
import hashlib
from datetime import datetime

from icalendar import Calendar, Event
from sqlalchemy.orm import Session

from app.db.models.review import Snapshot, SnapshotEvent
from app.modules.core_ingest.canonical_coercion import parse_iso_datetime
from app.modules.core_ingest.time_utils import as_utc
from app.modules.evidence.store import save_ics


def materialize_change_snapshot(
    *,
    db: Session,
    input_id: int,
    event_payload: dict | None,
    fallback_json: dict | None,
    retrieved_at: datetime,
) -> int | None:
    content_bytes = build_snapshot_content_bytes(event_payload=event_payload, fallback_json=fallback_json)
    snapshot_event_payload = build_snapshot_event_payload(event_payload=event_payload, fallback_json=fallback_json)
    if content_bytes is None or snapshot_event_payload is None:
        return None

    evidence_key = save_ics(input_id, content_bytes, retrieved_at)
    snapshot = Snapshot(
        input_id=input_id,
        retrieved_at=as_utc(retrieved_at),
        content_hash=hashlib.sha256(content_bytes).hexdigest(),
        event_count=1,
        raw_evidence_key=evidence_key,
    )
    db.add(snapshot)
    db.flush()
    db.add(
        SnapshotEvent(
            snapshot_id=snapshot.id,
            uid=snapshot_event_payload["uid"],
            course_label=snapshot_event_payload["course_label"],
            title=snapshot_event_payload["title"],
            start_at_utc=snapshot_event_payload["start_at_utc"],
            end_at_utc=snapshot_event_payload["end_at_utc"],
        )
    )
    db.flush()
    return int(snapshot.id)


def build_snapshot_content_bytes(*, event_payload: dict | None, fallback_json: dict | None) -> bytes | None:
    raw_component = _decode_raw_component(event_payload=event_payload)
    if raw_component is not None:
        return _wrap_component_as_calendar(raw_component)

    snapshot_event_payload = build_snapshot_event_payload(event_payload=event_payload, fallback_json=fallback_json)
    if snapshot_event_payload is None:
        return None

    calendar = Calendar()
    calendar.add("prodid", "-//CalendarDIFF//Review Evidence//EN")
    calendar.add("version", "2.0")

    event = Event()
    event.add("uid", snapshot_event_payload["uid"])
    event.add("summary", snapshot_event_payload["title"])
    event.add("dtstart", snapshot_event_payload["start_at_utc"])
    event.add("dtend", snapshot_event_payload["end_at_utc"])
    course_label = snapshot_event_payload.get("course_label")
    if isinstance(course_label, str) and course_label.strip():
        event.add("description", f"Course: {course_label.strip()}")
    calendar.add_component(event)
    return bytes(calendar.to_ical())


def build_snapshot_event_payload(*, event_payload: dict | None, fallback_json: dict | None) -> dict | None:
    payload = event_payload if isinstance(event_payload, dict) else {}
    fallback = fallback_json if isinstance(fallback_json, dict) else {}
    source_canonical = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else {}

    uid = _first_non_empty_str(
        source_canonical.get("external_event_id"),
        payload.get("uid"),
        fallback.get("uid"),
    )
    title = _first_non_empty_str(
        source_canonical.get("source_title"),
        payload.get("title"),
        fallback.get("title"),
    )
    course_label = _first_non_empty_str(payload.get("course_label"), fallback.get("course_label")) or "Unknown"
    start_raw = _first_non_empty_str(
        source_canonical.get("source_dtstart_utc"),
        payload.get("start_at_utc"),
        fallback.get("start_at_utc"),
    )
    end_raw = _first_non_empty_str(
        source_canonical.get("source_dtend_utc"),
        payload.get("end_at_utc"),
        fallback.get("end_at_utc"),
    )
    if uid is None or title is None or start_raw is None or end_raw is None:
        return None

    start_at = parse_iso_datetime(start_raw, field="start_at_utc", uid=uid)
    end_at = parse_iso_datetime(end_raw, field="end_at_utc", uid=uid)
    return {
        "uid": uid[:255],
        "title": title[:512],
        "course_label": course_label[:64],
        "start_at_utc": start_at,
        "end_at_utc": end_at,
    }


def _decode_raw_component(*, event_payload: dict | None) -> bytes | None:
    if not isinstance(event_payload, dict):
        return None
    raw_component = event_payload.get("raw_ics_component_b64")
    if not isinstance(raw_component, str) or not raw_component:
        return None
    try:
        return base64.b64decode(raw_component.encode("utf-8"), validate=True)
    except Exception:
        return None


def _wrap_component_as_calendar(component_bytes: bytes) -> bytes:
    try:
        body = component_bytes.decode("utf-8").strip()
    except Exception:
        return component_bytes
    if "BEGIN:VCALENDAR" in body and "END:VCALENDAR" in body:
        return body.encode("utf-8")
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//CalendarDIFF//Review Evidence//EN\r\n"
        f"{body}\r\n"
        "END:VCALENDAR\r\n"
    ).encode("utf-8")


def _first_non_empty_str(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


__all__ = [
    "build_snapshot_content_bytes",
    "build_snapshot_event_payload",
    "materialize_change_snapshot",
]
