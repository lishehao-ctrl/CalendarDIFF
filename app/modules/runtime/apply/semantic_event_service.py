from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time, timezone

from pydantic import BaseModel

from app.modules.common.course_identity import (
    course_display_name,
    normalize_label_token,
    normalized_course_identity_key,
    parse_course_display,
)
from app.modules.common.payload_schemas import LinkSignals, SemanticEventDraft

SEMANTIC_ID_NAMESPACE = "course_raw_type"
_EVENT_NAME_NOISE = re.compile(r"\s+")
def normalize_event_name_for_identity(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return "untitled"
    raw = re.sub(r"[^a-z0-9]+", " ", raw)
    raw = _EVENT_NAME_NOISE.sub(" ", raw).strip()
    return raw[:160] or "untitled"


def normalize_time_precision(value: object) -> str:
    if isinstance(value, str) and value.strip().lower() == "date_only":
        return "date_only"
    return "datetime"


def derive_time_precision(*, raw_datetime_value: object) -> str:
    if not isinstance(raw_datetime_value, str):
        return "datetime"
    cleaned = raw_datetime_value.strip()
    return "date_only" if cleaned and "T" not in cleaned.upper() else "datetime"


def split_due_parts(*, due_at: datetime | None, time_precision: str) -> tuple[date | None, time | None, str]:
    if due_at is None:
        return None, None, normalize_time_precision(time_precision)
    normalized_precision = normalize_time_precision(time_precision)
    if normalized_precision == "date_only":
        return due_at.date(), None, normalized_precision
    return due_at.date(), due_at.timetz().replace(tzinfo=None), normalized_precision


def normalize_semantic_event(raw: object, *, fallback_due_raw: object | None = None) -> dict:
    if isinstance(raw, BaseModel):
        raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict):
        raw = {}
    confidence = raw.get("confidence")
    evidence = raw.get("evidence")
    model = SemanticEventDraft.model_validate(
        {
            "uid": raw.get("uid"),
            "family_id": raw.get("family_id"),
            "family_name": raw.get("family_name"),
            "course_dept": raw.get("course_dept"),
            "course_number": raw.get("course_number"),
            "course_suffix": raw.get("course_suffix"),
            "course_quarter": raw.get("course_quarter"),
            "course_year2": raw.get("course_year2"),
            "raw_type": raw.get("raw_type"),
            "event_name": raw.get("event_name"),
            "ordinal": raw.get("ordinal"),
            "due_date": raw.get("due_date"),
            "due_time": raw.get("due_time"),
            "time_precision": raw.get("time_precision") or derive_time_precision(raw_datetime_value=fallback_due_raw),
            "confidence": confidence if isinstance(confidence, (int, float)) else 0.0,
            "evidence": evidence if isinstance(evidence, str) else "",
        }
    )
    payload = model.model_dump(mode="json")
    if payload["time_precision"] == "date_only":
        payload["due_time"] = None
    return payload


def normalize_semantic_parse(raw: object) -> dict:
    return normalize_semantic_event(raw)


def draft_from_course_and_semantic(*, course_parse: dict | None, semantic_parse: dict | None) -> dict:
    course_parse = course_parse if isinstance(course_parse, dict) else {}
    semantic_parse = semantic_parse if isinstance(semantic_parse, dict) else {}
    confidence = semantic_parse.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = course_parse.get("confidence")
    evidence = semantic_parse.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        evidence = course_parse.get("evidence")
    return normalize_semantic_event(
        {
            "course_dept": course_parse.get("dept"),
            "course_number": course_parse.get("number"),
            "course_suffix": course_parse.get("suffix"),
            "course_quarter": course_parse.get("quarter"),
            "course_year2": course_parse.get("year2"),
            "raw_type": semantic_parse.get("raw_type"),
            "event_name": semantic_parse.get("event_name"),
            "ordinal": semantic_parse.get("ordinal"),
            "due_date": semantic_parse.get("due_date"),
            "due_time": semantic_parse.get("due_time"),
            "time_precision": semantic_parse.get("time_precision"),
            "confidence": confidence,
            "evidence": evidence,
        },
        fallback_due_raw=semantic_parse.get("due_date"),
    )


def build_semantic_event_payload(
    *,
    semantic_draft: dict,
    source_facts: dict,
    family_id: int | None,
    family_name: str | None,
    raw_type: str | None,
    entity_uid: str,
) -> dict:
    normalized = normalize_semantic_event(
        {
            **(semantic_draft if isinstance(semantic_draft, dict) else {}),
            "uid": entity_uid,
            "family_id": family_id,
            "family_name": family_name,
            "raw_type": raw_type if isinstance(raw_type, str) and raw_type.strip() else (semantic_draft or {}).get("raw_type"),
        },
        fallback_due_raw=source_facts.get("source_dtstart_utc") if isinstance(source_facts, dict) else None,
    )
    fallback_due_at = _parse_optional_datetime(source_facts.get("source_dtstart_utc")) if isinstance(source_facts, dict) else None
    fallback_due_date, fallback_due_time, fallback_precision = split_due_parts(
        due_at=fallback_due_at,
        time_precision=derive_time_precision(raw_datetime_value=source_facts.get("source_dtstart_utc") if isinstance(source_facts, dict) else None),
    )
    final_event_name = normalized.get("event_name") or normalized.get("raw_type") or _fallback_event_name(source_facts=source_facts)
    if normalized.get("due_date") is None and fallback_due_date is not None:
        normalized["due_date"] = fallback_due_date.isoformat()
    if (
        normalized.get("due_time") is None
        and fallback_due_time is not None
        and normalize_time_precision(normalized.get("time_precision")) != "date_only"
    ):
        normalized["due_time"] = fallback_due_time.isoformat()
    normalized["time_precision"] = normalize_time_precision(normalized.get("time_precision") or fallback_precision)
    if normalized["time_precision"] == "date_only":
        normalized["due_time"] = None
    normalized["event_name"] = str(final_event_name or "Untitled")[:512]
    return normalized


def normalize_course_identity(
    *,
    course_dept: str | None,
    course_number: int | None,
    course_suffix: str | None = None,
    course_quarter: str | None = None,
    course_year2: int | None = None,
) -> str:
    return normalized_course_identity_key(
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
    )


def semantic_due_datetime(*, due_date: date | None, due_time: time | None, time_precision: str) -> datetime | None:
    if due_date is None:
        return None
    if normalize_time_precision(time_precision) == "date_only" or due_time is None:
        return datetime(due_date.year, due_date.month, due_date.day, 23, 59, tzinfo=timezone.utc)
    return datetime.combine(due_date, due_time, tzinfo=timezone.utc)


def semantic_due_datetime_from_payload(payload: dict | BaseModel) -> datetime | None:
    normalized = normalize_semantic_event(payload)
    due_date_raw = normalized.get("due_date")
    due_time_raw = normalized.get("due_time")
    due_date_value = date.fromisoformat(due_date_raw) if isinstance(due_date_raw, str) and due_date_raw else None
    due_time_value = time.fromisoformat(due_time_raw) if isinstance(due_time_raw, str) and due_time_raw else None
    return semantic_due_datetime(
        due_date=due_date_value,
        due_time=due_time_value,
        time_precision=str(normalized.get("time_precision") or "datetime"),
    )


def semantic_event_json(payload: dict) -> dict:
    return normalize_semantic_event(payload)


def semantic_event_with_patch(base_payload: dict, patch: dict) -> dict:
    current = normalize_semantic_event(base_payload)
    merged = dict(current)
    for key, value in patch.items():
        if value is None and key not in {"due_time"}:
            continue
        merged[key] = value
    return normalize_semantic_event(merged)


def _fallback_event_name(*, source_facts: dict) -> str:
    title = source_facts.get("source_title") if isinstance(source_facts, dict) else None
    if isinstance(title, str) and title.strip():
        return title.strip()[:512]
    return "Untitled"


def _parse_optional_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


__all__ = [
    "LinkSignals",
    "SemanticEventDraft",
    "build_semantic_event_payload",
    "course_display_name",
    "derive_time_precision",
    "draft_from_course_and_semantic",
    "normalize_course_identity",
    "normalize_event_name_for_identity",
    "normalize_semantic_event",
    "normalize_semantic_parse",
    "normalize_time_precision",
    "parse_course_display",
    "semantic_due_datetime",
    "semantic_due_datetime_from_payload",
    "semantic_event_json",
    "semantic_event_with_patch",
    "split_due_parts",
]
