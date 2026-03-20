from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from app.modules.runtime.apply.semantic_event_service import draft_from_course_and_semantic

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


def build_semantic_parse(
    *,
    raw_type: str | None = None,
    event_name: str | None = None,
    ordinal: int | None = None,
    due_at: datetime | None = None,
    due_date: str | None = None,
    due_time: str | None = None,
    time_precision: str = "datetime",
    confidence: float = 0.0,
    evidence: str = "",
) -> dict:
    resolved_due_date = due_date
    resolved_due_time = due_time
    resolved_precision = time_precision
    if due_at is not None:
        utc_due = due_at.astimezone(timezone.utc) if due_at.tzinfo is not None else due_at.replace(tzinfo=timezone.utc)
        resolved_due_date = utc_due.date().isoformat()
        if time_precision == "date_only":
            resolved_due_time = None
            resolved_precision = "date_only"
        else:
            resolved_due_time = utc_due.timetz().replace(tzinfo=None).isoformat()
            resolved_precision = "datetime"
    return {
        "raw_type": raw_type,
        "event_name": event_name,
        "ordinal": ordinal,
        "due_date": resolved_due_date,
        "due_time": resolved_due_time,
        "time_precision": resolved_precision,
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
    semantic_parse: dict | None = None,
    work_item_parse: dict | None = None,
    event_parts: dict | None = None,
    link_signals: dict | None = None,
) -> dict:
    resolved_end = end_at or (start_at + timedelta(hours=1))
    resolved_semantic = semantic_parse or _infer_semantic_parse(title=title, due_at=start_at, work_item_parse=work_item_parse, event_parts=event_parts)
    semantic_event_draft = draft_from_course_and_semantic(
        course_parse=course_parse or build_course_parse(confidence=0.0),
        semantic_parse=resolved_semantic,
    )
    return {
        "source_facts": {
            "external_event_id": external_event_id,
            "source_title": title,
            "source_summary": title,
            "source_dtstart_utc": _as_utc_iso(start_at),
            "source_dtend_utc": _as_utc_iso(resolved_end),
            "status": status,
            "location": location,
            "organizer": organizer,
        },
        "semantic_event_draft": semantic_event_draft,
        "link_signals": link_signals or build_link_signals(),
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
    semantic_parse: dict | None = None,
    work_item_parse: dict | None = None,
    event_parts: dict | None = None,
    link_signals: dict | None = None,
) -> dict:
    end_at = (due_at + timedelta(hours=1)) if due_at is not None else None
    resolved_semantic = semantic_parse or _infer_semantic_parse(title=title, due_at=due_at, work_item_parse=work_item_parse, event_parts=event_parts)
    semantic_event_draft = draft_from_course_and_semantic(
        course_parse=course_parse or build_course_parse(confidence=0.0),
        semantic_parse=resolved_semantic,
    )
    return {
        "message_id": message_id,
        "source_facts": {
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
        "semantic_event_draft": semantic_event_draft,
        "link_signals": link_signals or build_link_signals(),
    }


def _infer_semantic_parse(*, title: str, due_at: datetime | None, work_item_parse: dict | None, event_parts: dict | None) -> dict:
    explicit_raw_type = None
    explicit_ordinal = None
    explicit_confidence = 0.0
    explicit_evidence = title
    if isinstance(work_item_parse, dict):
        explicit_raw_type = work_item_parse.get("raw_kind_label") if isinstance(work_item_parse.get("raw_kind_label"), str) else None
        explicit_ordinal = work_item_parse.get("ordinal") if isinstance(work_item_parse.get("ordinal"), int) else None
        explicit_confidence = float(work_item_parse.get("confidence") or 0.0)
        explicit_evidence = str(work_item_parse.get("evidence") or explicit_evidence)
    if explicit_raw_type is None and isinstance(event_parts, dict):
        explicit_ordinal = explicit_ordinal if explicit_ordinal is not None else (event_parts.get("index") if isinstance(event_parts.get("index"), int) else None)
        explicit_confidence = max(explicit_confidence, float(event_parts.get("confidence") or 0.0))
        explicit_evidence = str(event_parts.get("evidence") or explicit_evidence)
    if explicit_raw_type is None:
        inferred_raw_type, inferred_ordinal = _infer_type_and_ordinal(title)
        explicit_raw_type = inferred_raw_type
        if explicit_ordinal is None:
            explicit_ordinal = inferred_ordinal
    return build_semantic_parse(
        raw_type=explicit_raw_type,
        event_name=title,
        ordinal=explicit_ordinal,
        due_at=due_at,
        confidence=explicit_confidence,
        evidence=explicit_evidence[:160],
    )


def _infer_type_and_ordinal(title: str) -> tuple[str | None, int | None]:
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
        match = pattern.search(title)
        if match:
            ordinal = int(match.group(1)) if match.lastindex and match.group(1) and match.group(1).isdigit() else None
            return label, ordinal
    return None, None


def _as_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()
