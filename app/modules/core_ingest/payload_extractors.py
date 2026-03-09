from __future__ import annotations

from datetime import timedelta

from app.modules.core_ingest.canonical_coercion import coerce_text, parse_optional_iso_datetime
from app.modules.core_ingest.merge_engine import normalize_topic_signature


def extract_source_canonical_from_calendar_payload(
    *,
    payload: dict,
    external_event_id: str,
) -> dict:
    raw = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else None
    if raw is None:
        raise RuntimeError("core_ingest_payload_invalid: calendar payload missing source_canonical")
    source_title = raw.get("source_title")
    source_summary = raw.get("source_summary")
    source_dtstart = raw.get("source_dtstart_utc")
    source_dtend = raw.get("source_dtend_utc")
    if not isinstance(source_title, str) or not source_title.strip():
        raise RuntimeError("core_ingest_payload_invalid: calendar payload missing source_canonical.source_title")
    if not isinstance(source_dtstart, str) or not source_dtstart.strip():
        raise RuntimeError("core_ingest_payload_invalid: calendar payload missing source_canonical.source_dtstart_utc")
    if not isinstance(source_dtend, str) or not source_dtend.strip():
        raise RuntimeError("core_ingest_payload_invalid: calendar payload missing source_canonical.source_dtend_utc")
    return {
        "external_event_id": external_event_id,
        "component_key": raw.get("component_key")
        if isinstance(raw.get("component_key"), str)
        else payload.get("component_key"),
        "source_title": source_title.strip()[:512],
        "source_summary": source_summary[:1024] if isinstance(source_summary, str) else None,
        "source_dtstart_utc": source_dtstart.strip(),
        "source_dtend_utc": source_dtend.strip(),
        "status": raw.get("status") if isinstance(raw.get("status"), str) else None,
        "location": raw.get("location") if isinstance(raw.get("location"), str) else None,
        "organizer": raw.get("organizer") if isinstance(raw.get("organizer"), str) else None,
    }


def extract_source_canonical_from_gmail_payload(*, payload: dict) -> dict:
    raw = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else None
    if raw is None:
        raise RuntimeError("core_ingest_payload_invalid: gmail payload missing source_canonical")
    parsed_due_at = parse_optional_iso_datetime(raw.get("source_dtstart_utc"))
    parsed_end = parse_optional_iso_datetime(raw.get("source_dtend_utc"))
    if parsed_due_at is not None and parsed_end is None:
        parsed_end = parsed_due_at + timedelta(hours=1)
    source_title = raw.get("source_title")
    if not isinstance(source_title, str) or not source_title.strip():
        raise RuntimeError("core_ingest_payload_invalid: gmail payload missing source_canonical.source_title")
    external_event_id = raw.get("external_event_id")
    if not isinstance(external_event_id, str) or not external_event_id.strip():
        raise RuntimeError("core_ingest_payload_invalid: gmail payload missing source_canonical.external_event_id")
    return {
        "external_event_id": external_event_id.strip(),
        "source_title": source_title.strip()[:512],
        "source_summary": raw.get("source_summary") if isinstance(raw.get("source_summary"), str) else None,
        "source_dtstart_utc": parsed_due_at.isoformat() if parsed_due_at is not None else None,
        "source_dtend_utc": parsed_end.isoformat() if parsed_end is not None else None,
        "time_anchor_confidence": float(raw.get("time_anchor_confidence"))
        if isinstance(raw.get("time_anchor_confidence"), (int, float))
        else 0.0,
        "from_header": raw.get("from_header") if isinstance(raw.get("from_header"), str) else None,
        "thread_id": raw.get("thread_id") if isinstance(raw.get("thread_id"), str) else None,
        "internal_date": raw.get("internal_date") if isinstance(raw.get("internal_date"), str) else None,
    }


def extract_enrichment_course_parse(*, payload: dict) -> dict:
    enrichment = payload.get("enrichment") if isinstance(payload.get("enrichment"), dict) else None
    if enrichment is None:
        raise RuntimeError("core_ingest_payload_invalid: payload missing enrichment")
    raw_course_parse = enrichment.get("course_parse")
    if not isinstance(raw_course_parse, dict):
        raise RuntimeError("core_ingest_payload_invalid: payload missing enrichment.course_parse")
    return normalize_course_parse(raw_course_parse)


def extract_enrichment_work_item_parse(*, payload: dict) -> dict:
    enrichment = payload.get("enrichment") if isinstance(payload.get("enrichment"), dict) else None
    if enrichment is None:
        raise RuntimeError("core_ingest_payload_invalid: payload missing enrichment")
    raw_work_item_parse = enrichment.get("work_item_parse")
    if not isinstance(raw_work_item_parse, dict):
        raise RuntimeError("core_ingest_payload_invalid: payload missing enrichment.work_item_parse")
    return normalize_work_item_parse(raw_work_item_parse)


def extract_enrichment_event_parts(*, payload: dict) -> dict:
    enrichment = payload.get("enrichment") if isinstance(payload.get("enrichment"), dict) else None
    if enrichment is None:
        raise RuntimeError("core_ingest_payload_invalid: payload missing enrichment")
    raw_event_parts = enrichment.get("event_parts")
    if not isinstance(raw_event_parts, dict):
        raise RuntimeError("core_ingest_payload_invalid: payload missing enrichment.event_parts")
    return normalize_event_parts(raw_event_parts)


def extract_link_signals(
    *,
    payload: dict,
    source_canonical: dict,
) -> dict:
    enrichment = payload.get("enrichment") if isinstance(payload.get("enrichment"), dict) else None
    if enrichment is None:
        raise RuntimeError("core_ingest_payload_invalid: payload missing enrichment")
    raw_signals = enrichment.get("link_signals")
    if not isinstance(raw_signals, dict):
        raise RuntimeError("core_ingest_payload_invalid: payload missing enrichment.link_signals")
    title = coerce_text(source_canonical.get("source_title")) or ""
    keywords = normalize_keyword_list(raw_signals.get("keywords"))
    exam_sequence = coerce_exam_sequence(raw_signals.get("exam_sequence"))
    location_text = coerce_text(raw_signals.get("location_text")) or coerce_text(source_canonical.get("location"))
    instructor_hint = (
        coerce_text(raw_signals.get("instructor_hint"))
        or coerce_text(source_canonical.get("from_header"))
        or coerce_text(source_canonical.get("organizer"))
    )
    from_header = coerce_text(source_canonical.get("from_header"))
    organizer = coerce_text(source_canonical.get("organizer"))
    thread_id = coerce_text(source_canonical.get("thread_id"))

    time_anchor_confidence = source_canonical.get("time_anchor_confidence")
    normalized_conf = float(time_anchor_confidence) if isinstance(time_anchor_confidence, (int, float)) else 0.0
    normalized_conf = max(0.0, min(1.0, normalized_conf))

    return {
        "keywords": keywords,
        "exam_sequence": exam_sequence,
        "location_text": location_text,
        "instructor_hint": instructor_hint,
        "from_header": from_header,
        "organizer": organizer,
        "thread_id": thread_id,
        "time_anchor_confidence": normalized_conf,
        "title_signature": normalize_topic_signature(title),
    }


def normalize_keyword_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        token = item.strip().lower()
        if token not in {"exam", "midterm", "final"}:
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def coerce_exam_sequence(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def normalize_course_parse(raw: object) -> dict:
    if not isinstance(raw, dict):
        return empty_course_parse()
    dept = raw.get("dept")
    number = raw.get("number")
    suffix = raw.get("suffix")
    quarter = raw.get("quarter")
    year2 = raw.get("year2")
    confidence = raw.get("confidence")
    evidence = raw.get("evidence")

    normalized_dept = dept.strip().upper()[:16] if isinstance(dept, str) and dept.strip() else None
    normalized_number = int(number) if isinstance(number, int) else None
    normalized_suffix = suffix.strip().upper()[:8] if isinstance(suffix, str) and suffix.strip() else None
    normalized_quarter = quarter.strip().upper() if isinstance(quarter, str) and quarter.strip() else None
    if normalized_quarter not in {"WI", "SP", "SU", "FA"}:
        normalized_quarter = None
    normalized_year2 = int(year2) if isinstance(year2, int) and 0 <= int(year2) <= 99 else None
    normalized_conf = float(confidence) if isinstance(confidence, (int, float)) else 0.0
    normalized_conf = max(0.0, min(1.0, normalized_conf))
    normalized_evidence = evidence.strip()[:80] if isinstance(evidence, str) else ""
    return {
        "dept": normalized_dept,
        "number": normalized_number,
        "suffix": normalized_suffix,
        "quarter": normalized_quarter,
        "year2": normalized_year2,
        "confidence": normalized_conf,
        "evidence": normalized_evidence,
    }


def normalize_work_item_parse(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {
            "raw_kind_label": None,
            "ordinal": None,
            "confidence": 0.0,
            "evidence": "",
        }
    raw_kind_label = raw.get("raw_kind_label")
    ordinal = raw.get("ordinal") if isinstance(raw.get("ordinal"), int) and int(raw.get("ordinal")) > 0 else None
    confidence = raw.get("confidence")
    evidence = raw.get("evidence")
    normalized_label = raw_kind_label.strip()[:128] if isinstance(raw_kind_label, str) and raw_kind_label.strip() else None
    normalized_confidence = float(confidence) if isinstance(confidence, (int, float)) else 0.0
    normalized_confidence = max(0.0, min(1.0, normalized_confidence))
    normalized_evidence = evidence.strip()[:120] if isinstance(evidence, str) else ""
    return {
        "raw_kind_label": normalized_label,
        "ordinal": ordinal,
        "confidence": normalized_confidence,
        "evidence": normalized_evidence,
    }


def normalize_event_parts(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {
            "type": None,
            "index": None,
            "qualifier": None,
            "confidence": 0.0,
            "evidence": "",
        }
    type_value = raw.get("type")
    index_value = raw.get("index")
    qualifier_value = raw.get("qualifier")
    confidence_value = raw.get("confidence")
    evidence_value = raw.get("evidence")

    normalized_type = type_value.strip().lower() if isinstance(type_value, str) and type_value.strip() else None
    if normalized_type not in {"exam", "deadline", "quiz", "project", "lecture", "other"}:
        normalized_type = None
    normalized_index = int(index_value) if isinstance(index_value, int) and int(index_value) > 0 else None
    normalized_qualifier = (
        qualifier_value.strip().lower()[:128]
        if isinstance(qualifier_value, str) and qualifier_value.strip()
        else None
    )
    normalized_confidence = float(confidence_value) if isinstance(confidence_value, (int, float)) else 0.0
    normalized_confidence = max(0.0, min(1.0, normalized_confidence))
    normalized_evidence = evidence_value.strip()[:120] if isinstance(evidence_value, str) else ""
    return {
        "type": normalized_type,
        "index": normalized_index,
        "qualifier": normalized_qualifier,
        "confidence": normalized_confidence,
        "evidence": normalized_evidence,
    }


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


__all__ = [
    "coerce_exam_sequence",
    "empty_course_parse",
    "extract_enrichment_course_parse",
    "extract_enrichment_event_parts",
    "extract_link_signals",
    "extract_source_canonical_from_calendar_payload",
    "extract_source_canonical_from_gmail_payload",
    "normalize_course_parse",
    "normalize_event_parts",
    "normalize_keyword_list",
]
