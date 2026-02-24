from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


RULE_VERSION = "email-rules-v1"
ACTIONABLE_EVENT_TYPES = {"schedule_change", "deadline", "exam", "assignment", "action_required"}

ISO_DT_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})\b")

SCHEDULE_TERMS_RE = re.compile(
    r"\b(schedule|reschedul|time change|location change|class moved|section moved|moved to|postponed|moved)\b",
    re.IGNORECASE,
)
DEADLINE_TERMS_RE = re.compile(r"\b(deadline|due|submit by|extended|extension)\b", re.IGNORECASE)
EXAM_TERMS_RE = re.compile(r"\b(quiz|midterm|final|exam|test)\b", re.IGNORECASE)
ASSIGNMENT_TERMS_RE = re.compile(r"\b(homework|assignment|project|pset|lab)\b", re.IGNORECASE)
ACTION_TERMS_RE = re.compile(
    r"\b(required action|please submit|please complete|must|need to|reply|send your|fill out|register)\b",
    re.IGNORECASE,
)
COURSE_RE = re.compile(r"\b([A-Z]{2,5})\s*-?\s*(\d{1,3}[A-Z]?)\b")


@dataclass(frozen=True)
class EmailRuleDecision:
    label: str
    confidence: float
    event_type: str | None
    due_at: datetime | None
    course_hint: str | None
    reasons: list[str]
    raw_extract: dict[str, str | None]
    proposed_title: str | None

    @property
    def actionable(self) -> bool:
        return self.label == "KEEP" and self.event_type in ACTIONABLE_EVENT_TYPES


def evaluate_email_rule(
    *,
    subject: str | None,
    snippet: str | None,
    from_header: str | None,
    internal_date: str | None,
    timezone_name: str = "UTC",
) -> EmailRuleDecision:
    subject_text = (subject or "").strip()
    snippet_text = (snippet or "").strip()
    from_text = (from_header or "").strip()
    combined = "\n".join(item for item in [subject_text, snippet_text, from_text] if item).lower()

    event_type = _detect_event_type(combined)
    due_at = _extract_due_at(combined, timezone_name=timezone_name)
    course_hint = _extract_first_course_hint((subject_text + "\n" + snippet_text).upper())

    if event_type in ACTIONABLE_EVENT_TYPES:
        label = "KEEP"
        confidence = 0.9 if due_at is not None else 0.82
    else:
        label = "DROP"
        confidence = 0.72

    reasons: list[str] = []
    if label == "KEEP":
        reasons.append(f"actionable signal detected: {event_type}")
        if due_at is not None:
            reasons.append("detected explicit due/time evidence")
    else:
        reasons.append("no actionable deadline/schedule signal in metadata+snippet")

    return EmailRuleDecision(
        label=label,
        confidence=round(confidence, 4),
        event_type=event_type if label == "KEEP" else None,
        due_at=due_at,
        course_hint=course_hint,
        reasons=reasons[:3],
        raw_extract={
            "deadline_text": ISO_DT_RE.search(combined).group(0) if ISO_DT_RE.search(combined) else None,
            "time_text": due_at.isoformat() if due_at is not None else None,
            "location_text": None,
        },
        proposed_title=subject_text or None,
    )


def _detect_event_type(text: str) -> str | None:
    if SCHEDULE_TERMS_RE.search(text):
        return "schedule_change"
    if DEADLINE_TERMS_RE.search(text):
        return "deadline"
    if EXAM_TERMS_RE.search(text):
        return "exam"
    if ASSIGNMENT_TERMS_RE.search(text):
        return "assignment"
    if ACTION_TERMS_RE.search(text):
        return "action_required"
    return None


def _extract_due_at(text: str, *, timezone_name: str) -> datetime | None:
    match = ISO_DT_RE.search(text)
    if match is None:
        return None
    raw = match.group(0)
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
        except Exception:
            parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_first_course_hint(text: str) -> str | None:
    match = COURSE_RE.search(text)
    if match is None:
        return None
    return f"{match.group(1).upper()} {match.group(2).upper()}"
