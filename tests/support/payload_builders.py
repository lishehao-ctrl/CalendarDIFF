from __future__ import annotations

from datetime import datetime, timedelta, timezone


def build_course_parse(
    *,
    dept: str | None = None,
    number: int | None = None,
    suffix: str | None = None,
    quarter: str | None = None,
    year2: int | None = None,
    confidence: float = 0.0,
    evidence: str = "",
) -> dict:
    return {
        "dept": dept,
        "number": number,
        "suffix": suffix,
        "quarter": quarter,
        "year2": year2,
        "confidence": float(confidence),
        "evidence": evidence,
    }


def build_event_parts(
    *,
    type: str | None = None,  # noqa: A002
    index: int | None = None,
    qualifier: str | None = None,
    confidence: float = 0.0,
    evidence: str = "",
) -> dict:
    return {
        "type": type,
        "index": index,
        "qualifier": qualifier,
        "confidence": float(confidence),
        "evidence": evidence,
    }


def build_link_signals(
    *,
    keywords: list[str] | None = None,
    exam_sequence: int | None = None,
    location_text: str | None = None,
    instructor_hint: str | None = None,
) -> dict:
    return {
        "keywords": list(keywords or []),
        "exam_sequence": exam_sequence,
        "location_text": location_text,
        "instructor_hint": instructor_hint,
    }


def build_calendar_payload(
    *,
    external_event_id: str,
    title: str,
    start_at: datetime,
    end_at: datetime | None = None,
    status: str | None = None,
    location: str | None = None,
    organizer: str | None = None,
    course_parse: dict | None = None,
    event_parts: dict | None = None,
    link_signals: dict | None = None,
) -> dict:
    resolved_end = end_at or (start_at + timedelta(hours=1))
    return {
        "source_canonical": {
            "external_event_id": external_event_id,
            "source_title": title,
            "source_summary": title,
            "source_dtstart_utc": _as_utc_iso(start_at),
            "source_dtend_utc": _as_utc_iso(resolved_end),
            "status": status,
            "location": location,
            "organizer": organizer,
        },
        "enrichment": {
            "course_parse": course_parse or build_course_parse(confidence=0.0),
            "event_parts": event_parts or build_event_parts(type="other", confidence=0.0),
            "link_signals": link_signals or build_link_signals(),
            "payload_schema_version": "obs_v3",
        },
    }


def build_gmail_payload(
    *,
    message_id: str,
    title: str,
    due_at: datetime | None,
    from_header: str | None = None,
    thread_id: str | None = None,
    internal_date: str | None = None,
    time_anchor_confidence: float = 0.0,
    course_parse: dict | None = None,
    event_parts: dict | None = None,
    link_signals: dict | None = None,
) -> dict:
    end_at = (due_at + timedelta(hours=1)) if due_at is not None else None
    return {
        "message_id": message_id,
        "source_canonical": {
            "external_event_id": message_id,
            "source_title": title,
            "source_summary": title,
            "source_dtstart_utc": _as_utc_iso(due_at) if due_at is not None else None,
            "source_dtend_utc": _as_utc_iso(end_at) if end_at is not None else None,
            "time_anchor_confidence": float(time_anchor_confidence),
            "from_header": from_header,
            "thread_id": thread_id,
            "internal_date": internal_date,
        },
        "enrichment": {
            "course_parse": course_parse or build_course_parse(confidence=0.0),
            "event_parts": event_parts or build_event_parts(type="other", confidence=0.0),
            "link_signals": link_signals or build_link_signals(),
            "payload_schema_version": "obs_v3",
        },
    }


def _as_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()
