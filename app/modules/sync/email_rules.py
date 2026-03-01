from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


RULE_VERSION = "email-rules-v1"
ACTIONABLE_EVENT_TYPES = {"schedule_change", "deadline", "exam", "assignment", "action_required"}

SCHEDULE_SINGLE_TERMS = {"schedule", "postponed", "moved"}
SCHEDULE_PREFIX_TERMS = ("reschedul",)
SCHEDULE_PHRASES = (
    ("time", "change"),
    ("location", "change"),
    ("class", "moved"),
    ("section", "moved"),
    ("moved", "to"),
)

DEADLINE_SINGLE_TERMS = {"deadline", "due", "extended", "extension"}
DEADLINE_PHRASES = (("submit", "by"),)
EXAM_TERMS = {"quiz", "midterm", "final", "exam", "test"}
ASSIGNMENT_TERMS = {"homework", "assignment", "project", "pset", "lab"}
ACTION_SINGLE_TERMS = {"must", "reply", "register"}
ACTION_PHRASES = (
    ("required", "action"),
    ("please", "submit"),
    ("please", "complete"),
    ("need", "to"),
    ("send", "your"),
    ("fill", "out"),
)

COURSE_PREFIX_BLACKLIST = {
    "ANNOUNCEMENT",
    "ASSIGNMENT",
    "CLASS",
    "COURSE",
    "DEADLINE",
    "DISCUSSION",
    "EXAM",
    "FINAL",
    "HOMEWORK",
    "LAB",
    "LECTURE",
    "MODULE",
    "PROJECT",
    "QUIZ",
    "READING",
    "SECTION",
    "TEST",
    "WEEK",
}

MONTH_NAME_TO_NUMBER = {
    "JAN": 1,
    "JANUARY": 1,
    "FEB": 2,
    "FEBRUARY": 2,
    "MAR": 3,
    "MARCH": 3,
    "APR": 4,
    "APRIL": 4,
    "MAY": 5,
    "JUN": 6,
    "JUNE": 6,
    "JUL": 7,
    "JULY": 7,
    "AUG": 8,
    "AUGUST": 8,
    "SEP": 9,
    "SEPT": 9,
    "SEPTEMBER": 9,
    "OCT": 10,
    "OCTOBER": 10,
    "NOV": 11,
    "NOVEMBER": 11,
    "DEC": 12,
    "DECEMBER": 12,
}

TIMEZONE_OFFSETS_HOURS = {
    "UTC": 0,
    "GMT": 0,
    "PT": -8,
    "PST": -8,
    "PDT": -7,
    "MT": -7,
    "MST": -7,
    "MDT": -6,
    "CT": -6,
    "CST": -6,
    "CDT": -5,
    "ET": -5,
    "EST": -5,
    "EDT": -4,
}


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
    score: float
    decision_origin: str = "rule"

    @property
    def actionable(self) -> bool:
        return self.label == "KEEP" and self.event_type in ACTIONABLE_EVENT_TYPES


def evaluate_email_rule(
    *,
    subject: str | None,
    snippet: str | None,
    body_text: str | None,
    from_header: str | None,
    internal_date: str | None,
    timezone_name: str = "UTC",
) -> EmailRuleDecision:
    subject_text = (subject or "").strip()
    snippet_text = (snippet or "").strip()
    body_plain = (body_text or "").strip()
    from_text = (from_header or "").strip()
    combined_raw = "\n".join(item for item in [subject_text, snippet_text, body_plain, from_text] if item)
    combined = combined_raw.lower()

    event_type = _detect_event_type(combined)
    due_at, due_text = _extract_due_at(combined_raw, internal_date=internal_date, timezone_name=timezone_name)
    course_hint = _extract_first_course_hint((subject_text + "\n" + snippet_text).upper())

    if event_type in ACTIONABLE_EVENT_TYPES:
        label = "KEEP"
        confidence = 0.9 if due_at is not None else 0.82
    else:
        label = "DROP"
        confidence = 0.72
    score = _compute_rule_score(event_type=event_type, due_at=due_at, course_hint=course_hint)

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
            "deadline_text": due_text,
            "time_text": due_at.isoformat() if due_at is not None else None,
            "location_text": None,
        },
        proposed_title=subject_text or None,
        score=score,
        decision_origin="rule",
    )


def _detect_event_type(text: str) -> str | None:
    tokens = _tokenize(text)
    if _has_schedule_signal(tokens):
        return "schedule_change"
    if _has_deadline_signal(tokens):
        return "deadline"
    if any(token in EXAM_TERMS for token in tokens):
        return "exam"
    if any(token in ASSIGNMENT_TERMS for token in tokens):
        return "assignment"
    if _has_action_signal(tokens):
        return "action_required"
    return None


def _extract_due_at(text: str, *, internal_date: str | None, timezone_name: str) -> tuple[datetime | None, str | None]:
    local_tz = _resolve_timezone(timezone_name)
    tokens = _scan_due_tokens(text)
    default_year = _resolve_default_year(internal_date, local_tz)

    for token in tokens:
        parsed_iso = _parse_iso_datetime_token(token, local_tz)
        if parsed_iso is not None:
            return parsed_iso, token

    for index in range(len(tokens)):
        mdy_candidate = _parse_mdy_due(tokens, start=index, default_year=default_year, fallback_tz=local_tz)
        if mdy_candidate is not None:
            return mdy_candidate

        month_day_candidate = _parse_month_day_due(
            tokens,
            start=index,
            default_year=default_year,
            fallback_tz=local_tz,
        )
        if month_day_candidate is not None:
            return month_day_candidate

    return None, None


def _resolve_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return ZoneInfo("UTC")


def _extract_first_course_hint(text: str) -> str | None:
    tokens = _tokenize(text.upper())
    for idx, token in enumerate(tokens):
        compact_course = _normalize_compact_course_token(token)
        if compact_course is not None:
            return compact_course

        if not _is_subject_token(token):
            continue
        if idx + 1 >= len(tokens):
            continue

        number = _normalize_number_token(tokens[idx + 1], max_digits=3)
        if number is None:
            continue
        return f"{token} {number}"
    return None


def _compute_rule_score(*, event_type: str | None, due_at: datetime | None, course_hint: str | None) -> float:
    strong_actionable_event_types = {"deadline", "exam", "assignment", "schedule_change"}
    if event_type in strong_actionable_event_types and due_at is not None:
        return 1.0
    if event_type is None and due_at is None and course_hint is None:
        return -1.0
    return 0.0


def _has_schedule_signal(tokens: list[str]) -> bool:
    if any(token in SCHEDULE_SINGLE_TERMS for token in tokens):
        return True
    if any(any(token.startswith(prefix) for prefix in SCHEDULE_PREFIX_TERMS) for token in tokens):
        return True
    return any(_contains_sequence(tokens, phrase) for phrase in SCHEDULE_PHRASES)


def _has_deadline_signal(tokens: list[str]) -> bool:
    if any(token in DEADLINE_SINGLE_TERMS for token in tokens):
        return True
    return any(_contains_sequence(tokens, phrase) for phrase in DEADLINE_PHRASES)


def _has_action_signal(tokens: list[str]) -> bool:
    if any(token in ACTION_SINGLE_TERMS for token in tokens):
        return True
    return any(_contains_sequence(tokens, phrase) for phrase in ACTION_PHRASES)


def _contains_sequence(tokens: list[str], phrase: tuple[str, ...]) -> bool:
    width = len(phrase)
    if width == 0 or len(tokens) < width:
        return False
    for idx in range(0, len(tokens) - width + 1):
        if tuple(tokens[idx : idx + width]) == phrase:
            return True
    return False


def _scan_due_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in text.replace("\n", " ").split():
        cleaned = _clean_token(raw)
        if cleaned:
            tokens.append(cleaned)
    return tokens


def _clean_token(token: str) -> str:
    return token.strip(".,;!?()[]{}<>\"'")


def _parse_iso_datetime_token(token: str, fallback_tz: ZoneInfo) -> datetime | None:
    if "T" not in token or "-" not in token:
        return None
    candidate = token
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=fallback_tz)
    return parsed.astimezone(timezone.utc)


def _parse_mdy_due(
    tokens: list[str],
    *,
    start: int,
    default_year: int,
    fallback_tz: ZoneInfo,
) -> tuple[datetime | None, str | None] | None:
    date_token = tokens[start]
    parsed_date = _parse_mdy_date_token(date_token, default_year=default_year)
    if parsed_date is None:
        return None
    year, month, day = parsed_date

    if start + 2 >= len(tokens):
        return None
    parsed_time = _parse_time_token(tokens[start + 1])
    am_pm = _normalize_am_pm(tokens[start + 2])
    if parsed_time is None or am_pm is None:
        return None

    tzinfo: ZoneInfo | timezone = fallback_tz
    end = start + 3
    if start + 3 < len(tokens):
        resolved_tz = _resolve_fixed_offset_tz(tokens[start + 3])
        if resolved_tz is not None:
            tzinfo = resolved_tz
            end += 1

    hour_24 = _to_24_hour(parsed_time[0], am_pm)
    minute = parsed_time[1]
    try:
        due_local = datetime(year, month, day, hour_24, minute, tzinfo=tzinfo)
    except ValueError:
        return None
    return due_local.astimezone(timezone.utc), " ".join(tokens[start:end])


def _parse_month_day_due(
    tokens: list[str],
    *,
    start: int,
    default_year: int,
    fallback_tz: ZoneInfo,
) -> tuple[datetime | None, str | None] | None:
    month = _parse_month_token(tokens[start])
    if month is None or start + 3 >= len(tokens):
        return None

    day = _parse_day_token(tokens[start + 1])
    if day is None:
        return None

    cursor = start + 2
    year = default_year
    explicit_year = _parse_year_token(tokens[cursor])
    if explicit_year is not None:
        year = explicit_year
        cursor += 1
        if cursor + 1 >= len(tokens):
            return None

    parsed_time = _parse_time_token(tokens[cursor])
    am_pm = _normalize_am_pm(tokens[cursor + 1]) if cursor + 1 < len(tokens) else None
    if parsed_time is None or am_pm is None:
        return None
    cursor += 2

    tzinfo: ZoneInfo | timezone = fallback_tz
    if cursor < len(tokens):
        resolved_tz = _resolve_fixed_offset_tz(tokens[cursor])
        if resolved_tz is not None:
            tzinfo = resolved_tz
            cursor += 1

    hour_24 = _to_24_hour(parsed_time[0], am_pm)
    minute = parsed_time[1]
    try:
        due_local = datetime(year, month, day, hour_24, minute, tzinfo=tzinfo)
    except ValueError:
        return None
    return due_local.astimezone(timezone.utc), " ".join(tokens[start:cursor])


def _parse_mdy_date_token(token: str, *, default_year: int) -> tuple[int, int, int] | None:
    parts = token.split("/")
    if len(parts) not in {2, 3}:
        return None
    if any(not part.isdigit() for part in parts):
        return None

    month = int(parts[0])
    day = int(parts[1])
    year = default_year
    if len(parts) == 3:
        year_raw = int(parts[2])
        year = year_raw + 2000 if year_raw < 100 else year_raw

    if month < 1 or month > 12 or day < 1 or day > 31:
        return None
    return year, month, day


def _parse_month_token(token: str) -> int | None:
    normalized = token.strip().upper()
    return MONTH_NAME_TO_NUMBER.get(normalized)


def _parse_day_token(token: str) -> int | None:
    digits: list[str] = []
    for ch in token:
        if ch.isdigit():
            digits.append(ch)
        else:
            break
    if not digits:
        return None
    day = int("".join(digits))
    if day < 1 or day > 31:
        return None
    return day


def _parse_year_token(token: str) -> int | None:
    if not token.isdigit() or len(token) != 4:
        return None
    year = int(token)
    if year < 1900 or year > 2300:
        return None
    return year


def _parse_time_token(token: str) -> tuple[int, int] | None:
    parts = token.split(":")
    if len(parts) not in {2, 3}:
        return None
    if not parts[0].isdigit() or not parts[1].isdigit():
        return None
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 1 or hour > 12 or minute < 0 or minute > 59:
        return None
    return hour, minute


def _normalize_am_pm(token: str) -> str | None:
    normalized = token.upper().replace(".", "")
    if normalized in {"AM", "PM"}:
        return normalized
    return None


def _to_24_hour(hour: int, am_pm: str) -> int:
    if am_pm == "AM":
        return 0 if hour == 12 else hour
    return 12 if hour == 12 else hour + 12


def _resolve_fixed_offset_tz(token: str) -> timezone | None:
    key = token.upper()
    offset_hours = TIMEZONE_OFFSETS_HOURS.get(key)
    if offset_hours is None:
        return None
    return timezone(timedelta(hours=offset_hours))


def _resolve_default_year(internal_date: str | None, local_tz: ZoneInfo) -> int:
    if isinstance(internal_date, str) and internal_date.strip():
        normalized = internal_date.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            pass
        else:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(local_tz).year
    return datetime.now(timezone.utc).astimezone(local_tz).year


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

    number = _normalize_number_token(compact[split_index:], max_digits=3)
    if number is None:
        return None
    return f"{subject} {number}"


def _is_subject_token(token: str) -> bool:
    return 2 <= len(token) <= 5 and token.isalpha() and token not in COURSE_PREFIX_BLACKLIST


def _normalize_number_token(token: str, *, max_digits: int) -> str | None:
    if not token:
        return None

    digit_end = 0
    while digit_end < len(token) and token[digit_end].isdigit():
        digit_end += 1

    if digit_end < 1 or digit_end > max_digits:
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
            chars.append(ch.lower())
        else:
            chars.append(" ")
    return [part for part in "".join(chars).split() if part]
