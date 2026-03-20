from __future__ import annotations

from datetime import timedelta

from app.modules.common.payload_schemas import LinkSignals, SemanticEventDraft, SourceFacts
from app.modules.runtime.apply.source_facts_coercion import coerce_text, parse_optional_iso_datetime
from app.modules.runtime.apply.semantic_event_service import (
    derive_time_precision,
    normalize_semantic_event,
)


def extract_source_facts_from_calendar_payload(
    *,
    payload: dict,
    external_event_id: str,
) -> dict:
    raw = payload.get("source_facts") if isinstance(payload.get("source_facts"), dict) else None
    if raw is None:
        raise RuntimeError("runtime_apply_payload_invalid: calendar payload missing source_facts")
    source_title = raw.get("source_title")
    source_summary = raw.get("source_summary")
    source_dtstart = raw.get("source_dtstart_utc")
    source_dtend = raw.get("source_dtend_utc")
    if not isinstance(source_title, str) or not source_title.strip():
        raise RuntimeError("runtime_apply_payload_invalid: calendar payload missing source_facts.source_title")
    if not isinstance(source_dtstart, str) or not source_dtstart.strip():
        raise RuntimeError("runtime_apply_payload_invalid: calendar payload missing source_facts.source_dtstart_utc")
    if not isinstance(source_dtend, str) or not source_dtend.strip():
        raise RuntimeError("runtime_apply_payload_invalid: calendar payload missing source_facts.source_dtend_utc")
    source_facts = SourceFacts.model_validate(
        {
            "external_event_id": external_event_id,
            "component_key": raw.get("component_key") if isinstance(raw.get("component_key"), str) else payload.get("component_key"),
            "source_title": source_title.strip()[:512],
            "source_summary": source_summary[:1024] if isinstance(source_summary, str) else None,
            "source_dtstart_utc": source_dtstart.strip(),
            "source_dtend_utc": source_dtend.strip(),
            "status": raw.get("status") if isinstance(raw.get("status"), str) else None,
            "location": raw.get("location") if isinstance(raw.get("location"), str) else None,
            "organizer": raw.get("organizer") if isinstance(raw.get("organizer"), str) else None,
            "source_time_precision": derive_time_precision(raw_datetime_value=source_dtstart),
        }
    )
    return source_facts.model_dump(mode="json")


def extract_source_facts_from_gmail_payload(*, payload: dict) -> dict:
    raw = payload.get("source_facts") if isinstance(payload.get("source_facts"), dict) else None
    if raw is None:
        raise RuntimeError("runtime_apply_payload_invalid: gmail payload missing source_facts")
    raw_due_at = raw.get("source_dtstart_utc")
    parsed_due_at = parse_optional_iso_datetime(raw_due_at)
    parsed_end = parse_optional_iso_datetime(raw.get("source_dtend_utc"))
    if parsed_due_at is not None and parsed_end is None:
        parsed_end = parsed_due_at + timedelta(hours=1)
    source_title = raw.get("source_title")
    if not isinstance(source_title, str) or not source_title.strip():
        raise RuntimeError("runtime_apply_payload_invalid: gmail payload missing source_facts.source_title")
    external_event_id = raw.get("external_event_id")
    if not isinstance(external_event_id, str) or not external_event_id.strip():
        raise RuntimeError("runtime_apply_payload_invalid: gmail payload missing source_facts.external_event_id")
    source_facts = SourceFacts.model_validate(
        {
            "external_event_id": external_event_id.strip(),
            "source_title": source_title.strip()[:512],
            "source_summary": raw.get("source_summary") if isinstance(raw.get("source_summary"), str) else None,
            "source_dtstart_utc": parsed_due_at.isoformat() if parsed_due_at is not None else None,
            "source_dtend_utc": parsed_end.isoformat() if parsed_end is not None else None,
            "time_anchor_confidence": float(raw.get("time_anchor_confidence")) if isinstance(raw.get("time_anchor_confidence"), (int, float)) else 0.0,
            "from_header": raw.get("from_header") if isinstance(raw.get("from_header"), str) else None,
            "thread_id": raw.get("thread_id") if isinstance(raw.get("thread_id"), str) else None,
            "internal_date": raw.get("internal_date") if isinstance(raw.get("internal_date"), str) else None,
            "source_time_precision": derive_time_precision(raw_datetime_value=raw_due_at),
        }
    )
    return source_facts.model_dump(mode="json")


def extract_semantic_event_draft(*, payload: dict, source_facts: dict | None = None) -> dict:
    raw = payload.get("semantic_event_draft")
    if not isinstance(raw, dict):
        raise RuntimeError("runtime_apply_payload_invalid: payload missing semantic_event_draft")
    draft = SemanticEventDraft.model_validate(
        normalize_semantic_event(
            raw,
            fallback_due_raw=source_facts.get("source_dtstart_utc") if isinstance(source_facts, dict) else None,
        )
    )
    return draft.model_dump(mode="json")


def extract_course_parse(*, payload: dict, source_facts: dict | None = None) -> dict:
    draft = extract_semantic_event_draft(payload=payload, source_facts=source_facts)
    return {
        "dept": draft.get("course_dept"),
        "number": draft.get("course_number"),
        "suffix": draft.get("course_suffix"),
        "quarter": draft.get("course_quarter"),
        "year2": draft.get("course_year2"),
        "confidence": draft.get("confidence") or 0.0,
        "evidence": draft.get("evidence") or "",
    }


def extract_link_signals(*, payload: dict, source_facts: dict) -> dict:
    raw_signals = payload.get("link_signals")
    if not isinstance(raw_signals, dict):
        raise RuntimeError("runtime_apply_payload_invalid: payload missing link_signals")
    normalized = LinkSignals.model_validate(
        {
            "keywords": raw_signals.get("keywords"),
            "exam_sequence": raw_signals.get("exam_sequence"),
            "location_text": coerce_text(raw_signals.get("location_text")) or coerce_text(source_facts.get("location")),
            "instructor_hint": coerce_text(raw_signals.get("instructor_hint")) or coerce_text(source_facts.get("from_header")) or coerce_text(source_facts.get("organizer")),
            "from_header": coerce_text(source_facts.get("from_header")),
            "organizer": coerce_text(source_facts.get("organizer")),
            "thread_id": coerce_text(source_facts.get("thread_id")),
            "time_anchor_confidence": source_facts.get("time_anchor_confidence"),
        }
    )
    return normalized.model_dump(mode="json")


def empty_course_parse() -> dict:
    return {
        "dept": None,
        "number": None,
        "suffix": None,
        "quarter": None,
        "year2": None,
        "confidence": 0.0,
        "evidence": "",
    }


def normalize_keyword_list(raw: object) -> list[str]:
    return LinkSignals.model_validate({"keywords": raw}).keywords


def coerce_exam_sequence(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


__all__ = [
    "coerce_exam_sequence",
    "empty_course_parse",
    "extract_course_parse",
    "extract_link_signals",
    "extract_semantic_event_draft",
    "extract_source_facts_from_calendar_payload",
    "extract_source_facts_from_gmail_payload",
    "normalize_keyword_list",
]
