#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mailbox
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator

try:
    from tools.labeling.label_emails_async import read_mbox_input_emails
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from label_emails_async import read_mbox_input_emails  # type: ignore[no-redef]

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = ROOT_DIR / "tools" / "labeling" / "schema" / "email_label.json"

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
TOKEN_RE = re.compile(r"\b(?:sk|rk|tok|token|apikey|api_key)[-_A-Za-z0-9]{8,}\b", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s)>\"']+")

COURSE_RE = re.compile(r"\b([A-Z]{2,5})\s*-?\s*(\d{1,3}[A-Z]?)\b")
ISO_DT_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})\b")
MONTH_DAY_RE = re.compile(
    r"\b("
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
    r")\s+(\d{1,2})(?:,\s*(\d{4}))?(?:\s*(?:at)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?)?\b",
    re.IGNORECASE,
)
TIME_HINT_RE = re.compile(r"\b(\d{1,2}:\d{2}\s*(?:am|pm)?)\b", re.IGNORECASE)
LOCATION_RE = re.compile(
    r"\b(?:room|location|classroom|building|zoom|venue)\b\s*[:\-]?\s*([A-Za-z0-9._/\- ]{2,80})",
    re.IGNORECASE,
)

SCHEDULE_TERMS_RE = re.compile(
    r"\b(schedule|reschedul|time change|location change|class moved|section moved|moved to|postponed|moved)\b",
    re.IGNORECASE,
)
DEADLINE_TERMS_RE = re.compile(
    r"\b(deadline|due|submit by|submission due|extended|extension|postponed deadline)\b",
    re.IGNORECASE,
)
EXAM_TERMS_RE = re.compile(r"\b(quiz|midterm|final|exam|test)\b", re.IGNORECASE)
ASSIGNMENT_TERMS_RE = re.compile(r"\b(homework|assignment|project|pset|lab)\b", re.IGNORECASE)
ACTION_TERMS_RE = re.compile(
    r"\b(required action|please submit|please complete|must|need to|reply|send your|fill out|register)\b",
    re.IGNORECASE,
)
GRADE_TERMS_RE = re.compile(r"\b(grade(?:s)? posted|grade update|scores? released|graded)\b", re.IGNORECASE)
ANNOUNCEMENT_TERMS_RE = re.compile(r"\b(announcement|logistics|reminder|office hour|lecture)\b", re.IGNORECASE)
DROP_NOISE_RE = re.compile(
    r"\b(daily digest|weekly digest|newsletter|maintenance notice|unsubscribe|no action required)\b",
    re.IGNORECASE,
)

EVENT_PRECEDENCE = (
    "schedule_change",
    "deadline",
    "exam",
    "assignment",
    "action_required",
    "grade",
    "announcement",
    "other",
)
ACTIONABLE_EVENTS = {"schedule_change", "deadline", "exam", "assignment", "action_required"}


@dataclass(frozen=True)
class RuleExtractConfig:
    input_jsonl: Path | None
    input_mbox: Path | None
    output_path: Path
    errors_path: Path
    schema_path: Path
    timezone: str


@dataclass(frozen=True)
class EmailInputRow:
    line_number: int
    email_id: str
    from_field: str | None
    subject: str | None
    date: str | None
    body_text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic rules extractor for academic email labels.")
    parser.add_argument("--input-jsonl", default=None, help="Input email JSONL path.")
    parser.add_argument("--input-mbox", default=None, help="Input mbox path.")
    parser.add_argument("--output", default="data/rules_labeled.jsonl", help="Output strict label JSONL path.")
    parser.add_argument("--errors", default="data/rules_errors.jsonl", help="Output error JSONL path.")
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA_PATH),
        help=f"Schema path for strict validation (default: {DEFAULT_SCHEMA_PATH}).",
    )
    parser.add_argument("--timezone", default="America/Los_Angeles", help="IANA timezone used for date parsing.")
    return parser.parse_args()


def sanitize_log_text(raw: str) -> str:
    text = TOKEN_RE.sub("<REDACTED_TOKEN>", raw)
    text = EMAIL_RE.sub("<REDACTED_EMAIL>", text)
    text = URL_RE.sub("<REDACTED_URL>", text)
    return text[:1200]


def build_config(args: argparse.Namespace) -> RuleExtractConfig:
    input_jsonl = Path(args.input_jsonl) if args.input_jsonl else None
    input_mbox = Path(args.input_mbox) if args.input_mbox else None
    if (input_jsonl is None) == (input_mbox is None):
        raise RuntimeError("Exactly one of --input-jsonl or --input-mbox is required.")
    if input_jsonl is not None and not input_jsonl.is_file():
        raise RuntimeError(f"Input JSONL not found: {input_jsonl}")
    if input_mbox is not None and not input_mbox.is_file():
        raise RuntimeError(f"Input mbox not found: {input_mbox}")

    schema_path = Path(args.schema)
    if not schema_path.is_file():
        raise RuntimeError(f"Schema not found: {schema_path}")

    timezone = str(args.timezone).strip()
    if not timezone:
        raise RuntimeError("--timezone cannot be blank")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"Invalid timezone: {timezone}") from exc

    return RuleExtractConfig(
        input_jsonl=input_jsonl,
        input_mbox=input_mbox,
        output_path=Path(args.output),
        errors_path=Path(args.errors),
        schema_path=schema_path,
        timezone=timezone,
    )


def iter_jsonl_rows(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Line {line_number} must be a JSON object")
            yield line_number, payload


def _to_input_row_from_jsonl(line_number: int, payload: dict[str, Any]) -> EmailInputRow:
    email_id = _coerce_text(payload.get("email_id"))
    body_text = _coerce_text(payload.get("body_text"))
    if not email_id:
        raise ValueError("missing email_id")
    if not body_text:
        raise ValueError("missing body_text")
    return EmailInputRow(
        line_number=line_number,
        email_id=email_id,
        from_field=_coerce_text(payload.get("from")),
        subject=_coerce_text(payload.get("subject")),
        date=_coerce_text(payload.get("date")),
        body_text=body_text,
    )


def read_email_rows(config: RuleExtractConfig) -> tuple[list[EmailInputRow], list[dict[str, Any]]]:
    rows: list[EmailInputRow] = []
    errors: list[dict[str, Any]] = []
    if config.input_jsonl is not None:
        for line_number, payload in iter_jsonl_rows(config.input_jsonl):
            try:
                rows.append(_to_input_row_from_jsonl(line_number, payload))
            except Exception as exc:
                errors.append(
                    {
                        "line_number": line_number,
                        "email_id": _coerce_text(payload.get("email_id")) or "unknown",
                        "error_type": "input_validation",
                        "message_sanitized": sanitize_log_text(str(exc)),
                    }
                )
        return rows, errors

    assert config.input_mbox is not None
    parsed_rows, parse_errors = read_mbox_input_emails(config.input_mbox, skip_ids=set())
    for idx, row in enumerate(parsed_rows, start=1):
        rows.append(
            EmailInputRow(
                line_number=idx,
                email_id=row.email_id,
                from_field=row.from_field,
                subject=row.subject,
                date=row.date,
                body_text=row.body_text,
            )
        )
    for idx, row in enumerate(parse_errors, start=1):
        errors.append(
            {
                "line_number": idx,
                "email_id": _coerce_text(row.get("email_id")) or "unknown",
                "error_type": _coerce_text(row.get("error_type")) or "mbox_parse",
                "message_sanitized": sanitize_log_text(_coerce_text(row.get("message_sanitized")) or "mbox parse error"),
            }
        )
    return rows, errors


def _coerce_text(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if value is None:
        return None
    return str(value).strip() or None


def _extract_course_hints(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in COURSE_RE.finditer(text):
        dept = match.group(1).upper()
        num = match.group(2).upper()
        normalized = f"{dept} {num}"
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _parse_base_email_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed


def _extract_due_iso(text: str, *, date_hint: str | None, timezone: ZoneInfo) -> tuple[str | None, str | None]:
    iso_match = ISO_DT_RE.search(text)
    if iso_match is not None:
        value = iso_match.group(0)
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone)
            return parsed.isoformat(), value
        except ValueError:
            pass

    base_dt = _parse_base_email_datetime(date_hint)
    default_year = base_dt.year if base_dt is not None else datetime.now(timezone).year
    text_lower = text.lower()
    for match in MONTH_DAY_RE.finditer(text_lower):
        month_word = match.group(1)
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else default_year
        hour_raw = match.group(4)
        minute_raw = match.group(5)
        ampm = match.group(6)

        month = _month_word_to_num(month_word)
        if month is None:
            continue
        hour = 23
        minute = 59
        if hour_raw is not None:
            hour = int(hour_raw)
            minute = int(minute_raw) if minute_raw else 0
            if ampm:
                marker = ampm.lower()
                if marker == "pm" and hour < 12:
                    hour += 12
                if marker == "am" and hour == 12:
                    hour = 0
        try:
            parsed = datetime(year, month, day, hour, minute, tzinfo=timezone)
        except ValueError:
            continue
        return parsed.isoformat(), match.group(0)
    return None, None


def _month_word_to_num(value: str) -> int | None:
    text = value.strip().lower()
    mapping = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    return mapping.get(text)


def _extract_location(text: str) -> str | None:
    match = LOCATION_RE.search(text)
    if match is None:
        return None
    return match.group(1).strip() or None


def _detect_event_type(text: str) -> str:
    lowered = text.lower()
    flags = {
        "schedule_change": bool(SCHEDULE_TERMS_RE.search(lowered)),
        "deadline": bool(DEADLINE_TERMS_RE.search(lowered)),
        "exam": bool(EXAM_TERMS_RE.search(lowered)),
        "assignment": bool(ASSIGNMENT_TERMS_RE.search(lowered)),
        "action_required": bool(ACTION_TERMS_RE.search(lowered)),
        "grade": bool(GRADE_TERMS_RE.search(lowered)),
        "announcement": bool(ANNOUNCEMENT_TERMS_RE.search(lowered)),
        "other": True,
    }
    for event_type in EVENT_PRECEDENCE:
        if flags.get(event_type):
            return event_type
    return "other"


def _build_reasons(*, label: str, event_type: str, noise_drop: bool, due_text: str | None) -> list[str]:
    reasons: list[str] = []
    if label == "DROP":
        if noise_drop:
            reasons.append("digest/newsletter style content without actionable deadline signal")
        reasons.append("no actionable schedule or deadline signal detected")
        return reasons[:3]

    mapping = {
        "schedule_change": "schedule or class time/location change signal detected",
        "deadline": "deadline or due-date language detected",
        "exam": "exam/quiz signal detected",
        "assignment": "assignment/homework/project signal detected",
        "action_required": "explicit required-action language detected",
        "grade": "grade update signal detected",
        "announcement": "course announcement/logistics signal detected",
        "other": "general course-related signal detected",
    }
    reasons.append(mapping.get(event_type, "course-related signal detected"))
    if due_text:
        reasons.append(f"time/deadline evidence: {due_text}")
    if event_type in ACTIONABLE_EVENTS:
        reasons.append("classified as actionable for downstream review")
    return reasons[:3]


def _build_row(row: EmailInputRow, *, timezone: ZoneInfo) -> dict[str, Any]:
    subject = row.subject or ""
    body = row.body_text or ""
    combined = f"{subject}\n{body}".strip()
    event_type = _detect_event_type(combined)
    noise_drop = bool(DROP_NOISE_RE.search(combined))
    keep = event_type != "other" and (not noise_drop or event_type in {"deadline", "exam", "assignment", "action_required", "schedule_change", "grade"})
    label = "KEEP" if keep else "DROP"

    due_iso, due_text = _extract_due_iso(combined, date_hint=row.date, timezone=timezone)
    location = _extract_location(combined)
    time_hint_match = TIME_HINT_RE.search(combined)
    time_text = due_iso or (time_hint_match.group(1) if time_hint_match is not None else None)

    if label == "DROP":
        event_type_out: str | None = None
        confidence = 0.9 if noise_drop else 0.72
        action_items: list[dict[str, Any]] = []
    else:
        event_type_out = event_type
        if event_type in ACTIONABLE_EVENTS and due_iso is not None:
            confidence = 0.92
        elif event_type in ACTIONABLE_EVENTS:
            confidence = 0.84
        elif event_type in {"grade", "announcement"}:
            confidence = 0.74
        else:
            confidence = 0.66

        action_items = []
        if event_type in ACTIONABLE_EVENTS:
            action = (subject.strip() or f"Review {event_type.replace('_', ' ')} update")[:240]
            action_items.append(
                {
                    "action": action,
                    "due_iso": due_iso,
                    "where": location,
                }
            )

    reasons = _build_reasons(label=label, event_type=event_type, noise_drop=noise_drop, due_text=due_text)
    course_hints = _extract_course_hints(combined.upper())
    raw_extract = {
        "deadline_text": due_text,
        "time_text": time_text,
        "location_text": location,
    }

    return {
        "email_id": row.email_id,
        "label": label,
        "confidence": round(float(confidence), 4),
        "reasons": reasons[:3],
        "course_hints": course_hints,
        "event_type": event_type_out,
        "action_items": action_items,
        "raw_extract": raw_extract,
        "notes": None,
    }


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_rules_extract(config: RuleExtractConfig) -> dict[str, Any]:
    schema = json.loads(config.schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    timezone = ZoneInfo(config.timezone)

    input_rows, initial_errors = read_email_rows(config)
    total_in = len(input_rows) + len(initial_errors)
    out_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = list(initial_errors)

    for row in input_rows:
        try:
            payload = _build_row(row, timezone=timezone)
            validator.validate(payload)
            out_rows.append(payload)
        except Exception as exc:
            error_rows.append(
                {
                    "line_number": row.line_number,
                    "email_id": row.email_id,
                    "error_type": "schema_validation",
                    "message_sanitized": sanitize_log_text(str(exc)),
                }
            )

    write_jsonl(config.output_path, out_rows)
    write_jsonl(config.errors_path, error_rows)

    summary = {
        "total_in": total_in,
        "output_rows": len(out_rows),
        "error_count": len(error_rows),
        "input_mode": "jsonl" if config.input_jsonl is not None else "mbox",
    }
    return summary


def main() -> int:
    try:
        config = build_config(parse_args())
        summary = run_rules_extract(config)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": sanitize_log_text(str(exc))}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
