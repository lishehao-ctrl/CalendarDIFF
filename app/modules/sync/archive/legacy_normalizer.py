from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.modules.sync.types import CanonicalEventInput, RawICSEvent

DEADLINE_KEYWORDS = {
    "assignment",
    "homework",
    "project",
    "milestone",
    "pset",
    "lab",
    "discussion",
    "quiz",
    "exam",
    "test",
    "midterm",
    "final",
    "deadline",
    "due",
    "submit",
    "deliverable",
    "report",
    "presentation",
}

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
    section_course = _extract_course_from_section_tag(summary) or _extract_course_from_section_tag(description)
    if section_course is not None:
        return section_course

    summary_course = _extract_course_from_summary(summary)
    if summary_course is not None:
        return summary_course

    return "Unknown"


def _extract_course_from_section_tag(text: str) -> str | None:
    upper = text.upper()
    for segment in upper.split("[")[1:]:
        bracket_content, _, _ = segment.partition("]")
        if not bracket_content:
            continue
        compact_head = bracket_content.split("_", 1)[0]
        normalized = _normalize_compact_course_token(compact_head)
        if normalized is not None:
            return normalized
    return None


def _extract_course_from_summary(summary: str) -> str | None:
    tokens = _tokenize(summary.upper())
    for idx, token in enumerate(tokens):
        compact_course = _normalize_compact_course_token(token)
        if compact_course is not None:
            return compact_course

        if not _is_subject_token(token):
            continue

        if idx + 1 >= len(tokens):
            continue
        number = _normalize_number_token(tokens[idx + 1])
        if number is None:
            continue
        return f"{token} {number}"
    return None


def _normalize_compact_course_token(token: str) -> str | None:
    compact = token.strip().upper()
    if not compact:
        return None

    split_index = 0
    while split_index < len(compact) and compact[split_index].isalpha():
        split_index += 1

    subject = compact[:split_index]
    if not _is_subject_token(subject):
        return None

    number = _normalize_number_token(compact[split_index:])
    if number is None:
        return None
    return f"{subject} {number}"


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_deadline_like_event(summary: str, description: str) -> bool:
    tokens = _tokenize((summary + "\n" + description).lower())
    return any(token in DEADLINE_KEYWORDS for token in tokens)


def _is_subject_token(token: str) -> bool:
    return 2 <= len(token) <= 6 and token.isalpha() and token not in COURSE_PREFIX_BLACKLIST


def _normalize_number_token(token: str) -> str | None:
    if not token:
        return None

    digit_end = 0
    while digit_end < len(token) and token[digit_end].isdigit():
        digit_end += 1

    if digit_end < 1 or digit_end > 4:
        return None

    suffix = token[digit_end:]
    if len(suffix) > 1:
        return None
    if suffix and not suffix.isalpha():
        return None
    if digit_end + len(suffix) != len(token):
        return None

    return token[:digit_end] + suffix


def _tokenize(text: str) -> list[str]:
    chars: list[str] = []
    for ch in text:
        if ch.isalnum():
            chars.append(ch)
        else:
            chars.append(" ")
    return [part for part in "".join(chars).split() if part]
