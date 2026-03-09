from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

HW_PATTERN = re.compile(r"\b(?:hw|homework)[\s_\-]*([0-9]+)\b", re.I)
PA_PATTERN = re.compile(r"\b(?:pa|programming assignment)[\s_\-]*([0-9]+)\b", re.I)
PSET_PATTERN = re.compile(r"\b(?:pset|problem set)[\s_\-]*([0-9]+)\b", re.I)
QUIZ_PATTERN = re.compile(r"\bquiz[\s_\-]*([0-9]+)\b", re.I)
EXAM_PATTERN = re.compile(r"\b(?:exam|midterm|final)[\s_\-]*([0-9]+)?\b", re.I)
PROJECT_PATTERN = re.compile(r"\bproject[\s_\-]*([0-9]+)\b", re.I)
LAB_PATTERN = re.compile(r"\blab[\s_\-]*([0-9]+)?\b", re.I)
PAPER_PATTERN = re.compile(r"\bpaper[\s_\-]*([0-9]+)?\b", re.I)


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


def build_work_item_parse(
    *,
    raw_kind_label: str | None = None,
    ordinal: int | None = None,
    confidence: float = 0.0,
    evidence: str = "",
) -> dict:
    return {
        "raw_kind_label": raw_kind_label,
        "ordinal": ordinal,
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
    work_item_parse: dict | None = None,
    event_parts: dict | None = None,
    link_signals: dict | None = None,
) -> dict:
    resolved_end = end_at or (start_at + timedelta(hours=1))
    resolved_event_parts = event_parts or build_event_parts(type="other", confidence=0.0)
    resolved_work_item_parse = work_item_parse or _infer_work_item_parse(title=title, event_parts=resolved_event_parts)
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
            "work_item_parse": resolved_work_item_parse,
            "event_parts": resolved_event_parts,
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
    work_item_parse: dict | None = None,
    event_parts: dict | None = None,
    link_signals: dict | None = None,
) -> dict:
    end_at = (due_at + timedelta(hours=1)) if due_at is not None else None
    resolved_event_parts = event_parts or build_event_parts(type="other", confidence=0.0)
    resolved_work_item_parse = work_item_parse or _infer_work_item_parse(title=title, event_parts=resolved_event_parts)
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
            "work_item_parse": resolved_work_item_parse,
            "event_parts": resolved_event_parts,
            "link_signals": link_signals or build_link_signals(),
            "payload_schema_version": "obs_v3",
        },
    }


def _infer_work_item_parse(*, title: str, event_parts: dict) -> dict:
    source_text = f"{title} {(event_parts.get('evidence') or '')}".strip()
    for label, pattern in (
        ("Homework", HW_PATTERN),
        ("Programming Assignment", PA_PATTERN),
        ("Problem Set", PSET_PATTERN),
        ("Quiz", QUIZ_PATTERN),
        ("Exam", EXAM_PATTERN),
        ("Project", PROJECT_PATTERN),
        ("Lab", LAB_PATTERN),
        ("Paper", PAPER_PATTERN),
    ):
        match = pattern.search(source_text)
        if match:
            ordinal = int(match.group(1)) if match.lastindex and match.group(1) and match.group(1).isdigit() else event_parts.get("index")
            return build_work_item_parse(
                raw_kind_label=label,
                ordinal=ordinal if isinstance(ordinal, int) and ordinal > 0 else None,
                confidence=float(event_parts.get("confidence") or 0.0),
                evidence=(event_parts.get("evidence") or title)[:120],
            )
    ordinal = event_parts.get("index") if isinstance(event_parts.get("index"), int) else None
    return build_work_item_parse(
        raw_kind_label=None,
        ordinal=ordinal,
        confidence=float(event_parts.get("confidence") or 0.0),
        evidence=(event_parts.get("evidence") or title)[:120],
    )


def _as_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()
