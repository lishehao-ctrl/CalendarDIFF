from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from app.modules.sync.types import CanonicalEventInput, RawICSEvent

SECTION_TAG_PATTERN = re.compile(r"\[([A-Z]{2,6}\d{1,4}[A-Z]?)(?:_[A-Z0-9]+){1,4}\]")
SUMMARY_COURSE_PATTERN = re.compile(r"\b([A-Z]{2,6})\s?(\d{1,4}[A-Z]?)\b")
COMPACT_COURSE_PATTERN = re.compile(r"^([A-Z]{2,6})(\d{1,4}[A-Z]?)$")
DEADLINE_LIKE_PATTERN = re.compile(
    r"\b("
    r"assignment|homework|project|milestone|pset|lab|discussion|quiz|exam|test|midterm|final|"
    r"deadline|due|submit|deliverable|report|presentation"
    r")\b",
    re.IGNORECASE,
)

COURSE_PREFIX_BLACKLIST = {
    "ASSIGNMENT",
    "CHAPTER",
    "CLASS",
    "COURSE",
    "DISCUSSION",
    "EXAM",
    "FINAL",
    "HW",
    "IN",
    "LAB",
    "LECTURE",
    "LESSON",
    "MIDTERM",
    "MODULE",
    "PART",
    "PROJECT",
    "QUIZ",
    "READING",
    "READINGS",
    "REFLECTION",
    "RQ",
    "SECTION",
    "TEST",
    "TOPIC",
    "UNIT",
    "WEEK",
    "WI",
    "SP",
    "SU",
    "FA",
}


def normalize_events(raw_events: list[RawICSEvent]) -> list[CanonicalEventInput]:
    normalized_by_uid: dict[str, CanonicalEventInput] = {}

    for raw in raw_events:
        if not is_deadline_like_event(raw.summary, raw.description):
            continue
        start_utc = _ensure_utc(raw.dtstart)
        end_utc = _ensure_utc(raw.dtend)
        title = raw.summary.strip() or "Untitled"
        course_label = infer_course_label(raw.summary, raw.description)

        uid = raw.uid.strip() if raw.uid else ""
        if not uid:
            uid = build_fingerprint_uid(title, start_utc, end_utc)

        normalized_by_uid[uid] = CanonicalEventInput(
            uid=uid,
            course_label=course_label,
            title=title,
            start_at_utc=start_utc,
            end_at_utc=end_utc,
        )

    return sorted(normalized_by_uid.values(), key=lambda item: item.uid)


def build_fingerprint_uid(title: str, start_at_utc: datetime, end_at_utc: datetime) -> str:
    payload = f"{title}|{start_at_utc.isoformat()}|{end_at_utc.isoformat()}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"fp:{digest}"


def infer_course_label(summary: str, description: str) -> str:
    summary_upper = summary.upper()
    description_upper = description.upper()

    section_course = _extract_course_from_section_tag(summary_upper) or _extract_course_from_section_tag(description_upper)
    if section_course is not None:
        return section_course

    summary_course = _extract_course_from_summary(summary_upper)
    if summary_course is not None:
        return summary_course

    return "Unknown"


def _extract_course_from_section_tag(text: str) -> str | None:
    for match in SECTION_TAG_PATTERN.finditer(text):
        token = match.group(1)
        normalized = _normalize_compact_course_token(token)
        if normalized is not None:
            return normalized
    return None


def _extract_course_from_summary(summary: str) -> str | None:
    for match in SUMMARY_COURSE_PATTERN.finditer(summary):
        subject = match.group(1)
        number = match.group(2)
        if subject in COURSE_PREFIX_BLACKLIST:
            continue
        return f"{subject} {number}"
    return None


def _normalize_compact_course_token(token: str) -> str | None:
    match = COMPACT_COURSE_PATTERN.match(token)
    if not match:
        return None

    subject = match.group(1)
    number = match.group(2)
    if subject in COURSE_PREFIX_BLACKLIST:
        return None
    return f"{subject} {number}"


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_deadline_like_event(summary: str, description: str) -> bool:
    text = f"{summary}\n{description}"
    return DEADLINE_LIKE_PATTERN.search(text) is not None
