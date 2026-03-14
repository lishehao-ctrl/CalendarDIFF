from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from icalendar import Calendar
from pydantic import BaseModel, Field, ValidationError, model_validator


class SourceTermWindowConfigError(ValueError):
    pass


class SourceTermWindowModel(BaseModel):
    term_key: str = Field(min_length=1, max_length=64)
    term_from: date
    term_to: date

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_order(self) -> "SourceTermWindowModel":
        if self.term_to < self.term_from:
            raise ValueError("term_to must be on or after term_from")
        return self


@dataclass(frozen=True)
class SourceTermWindow:
    term_key: str
    term_from: date
    term_to: date

    @property
    def bootstrap_from(self) -> date:
        return self.term_from - timedelta(days=30)

    @property
    def monitor_from(self) -> date:
        return self.term_from

    @property
    def monitor_until(self) -> date:
        return self.term_to + timedelta(days=30)

    @property
    def archive_after(self) -> date:
        return self.monitor_until

    def to_config_json(self) -> dict[str, str]:
        return {
            "term_key": self.term_key,
            "term_from": self.term_from.isoformat(),
            "term_to": self.term_to.isoformat(),
        }

    def contains_local_date(self, value: date | None) -> bool:
        if value is None:
            return False
        return self.bootstrap_from <= value <= self.monitor_until

    def contains_datetime(self, value: datetime | None, *, timezone_name: str | None) -> bool:
        local_date = datetime_to_local_date(value, timezone_name=timezone_name)
        return self.contains_local_date(local_date)

    def is_expired(self, *, now: datetime, timezone_name: str | None) -> bool:
        local_date = datetime_to_local_date(now, timezone_name=timezone_name)
        return local_date is not None and local_date > self.archive_after

    def has_started(self, *, now: datetime, timezone_name: str | None) -> bool:
        local_date = datetime_to_local_date(now, timezone_name=timezone_name)
        return local_date is not None and local_date >= self.monitor_from

    def monitor_start_at_utc(self, *, timezone_name: str | None) -> datetime:
        zone = _resolve_timezone(timezone_name)
        local_start = datetime.combine(self.monitor_from, time.min, tzinfo=zone)
        return local_start.astimezone(timezone.utc)

    def gmail_query_bounds(self) -> tuple[str, str]:
        start = self.bootstrap_from.strftime("%Y/%m/%d")
        end_exclusive = (self.monitor_until + timedelta(days=1)).strftime("%Y/%m/%d")
        return start, end_exclusive


TERM_WINDOW_KEYS = ("term_key", "term_from", "term_to")


def normalize_term_window_config(*, config: dict[str, Any], required: bool) -> dict[str, Any]:
    normalized = dict(config)
    present = [key for key in TERM_WINDOW_KEYS if key in normalized and normalized.get(key) not in (None, "")]
    if not present:
        if required:
            raise SourceTermWindowConfigError("config must include term_key, term_from, and term_to")
        return normalized
    if len(present) != len(TERM_WINDOW_KEYS):
        raise SourceTermWindowConfigError("config must include term_key, term_from, and term_to together")
    window = parse_term_window_config(normalized, required=True)
    normalized.update(window.to_config_json())
    return normalized


def parse_term_window_config(config: Any, *, required: bool) -> SourceTermWindow | None:
    if not isinstance(config, dict):
        if required:
            raise SourceTermWindowConfigError("config must be an object")
        return None
    subset = {key: config.get(key) for key in TERM_WINDOW_KEYS if key in config}
    if not subset:
        if required:
            raise SourceTermWindowConfigError("config must include term_key, term_from, and term_to")
        return None
    if len(subset) != len(TERM_WINDOW_KEYS):
        raise SourceTermWindowConfigError("config must include term_key, term_from, and term_to together")
    try:
        model = SourceTermWindowModel.model_validate(subset)
    except ValidationError as exc:
        raise SourceTermWindowConfigError(_term_window_validation_message(exc)) from exc
    return SourceTermWindow(term_key=model.term_key.strip(), term_from=model.term_from, term_to=model.term_to)


def _term_window_validation_message(exc: ValidationError) -> str:
    detail = exc.errors()[0] if exc.errors() else {}
    location = detail.get("loc") or ()
    message = detail.get("msg")
    field = location[-1] if location else None
    if isinstance(field, str) and field in TERM_WINDOW_KEYS:
        if isinstance(message, str) and message.strip():
            return f"invalid term window config: {field} ({message})"
        return f"invalid term window config: {field}"
    if isinstance(message, str) and message.strip():
        return f"invalid term window config: {message}"
    return "invalid term window config"


def parse_source_term_window(source: Any, *, required: bool = False) -> SourceTermWindow | None:
    source_config = getattr(source, "config", None)
    config_json = getattr(source_config, "config_json", None)
    return parse_term_window_config(config_json, required=required)


def source_timezone_name(source: Any) -> str | None:
    user = getattr(source, "user", None)
    value = getattr(user, "timezone_name", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "UTC"


def datetime_to_local_date(value: datetime | None, *, timezone_name: str | None) -> date | None:
    if value is None:
        return None
    zone = _resolve_timezone(timezone_name)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(zone).date()


def parse_iso_datetime(value: object) -> datetime | None:
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


def message_internal_date_in_window(*, internal_date: object, term_window: SourceTermWindow, timezone_name: str | None) -> bool:
    parsed = parse_iso_datetime(internal_date)
    return term_window.contains_datetime(parsed, timezone_name=timezone_name)


def semantic_due_date_in_window(
    *,
    semantic_payload: dict[str, Any] | None,
    fallback_datetime: datetime | None,
    term_window: SourceTermWindow,
    timezone_name: str | None,
) -> bool:
    if isinstance(semantic_payload, dict):
        due_date_raw = semantic_payload.get("due_date")
        if isinstance(due_date_raw, str) and due_date_raw.strip():
            try:
                due_date_value = date.fromisoformat(due_date_raw.strip())
            except ValueError:
                due_date_value = None
            else:
                return term_window.contains_local_date(due_date_value)
    return term_window.contains_datetime(fallback_datetime, timezone_name=timezone_name)


def calendar_component_in_window(
    *,
    component_ical_b64: object,
    term_window: SourceTermWindow,
    timezone_name: str | None,
) -> bool:
    if not isinstance(component_ical_b64, str) or not component_ical_b64.strip():
        return True
    component_datetime = extract_calendar_component_datetime(component_ical_b64)
    if component_datetime is not None:
        return term_window.contains_datetime(component_datetime, timezone_name=timezone_name)
    component_date = extract_calendar_component_date(component_ical_b64)
    if component_date is not None:
        return term_window.contains_local_date(component_date)
    return True


def extract_calendar_component_datetime(component_ical_b64: str) -> datetime | None:
    component = _parse_single_vevent(component_ical_b64)
    if component is None:
        return None
    for field_name in ("DUE", "DTSTART", "DTEND"):
        value = component.get(field_name)
        normalized = _normalize_ical_datetime(value)
        if normalized is not None:
            return normalized
    return None


def extract_calendar_component_date(component_ical_b64: str) -> date | None:
    component = _parse_single_vevent(component_ical_b64)
    if component is None:
        return None
    for field_name in ("DUE", "DTSTART", "DTEND"):
        value = component.get(field_name)
        normalized = _normalize_ical_date(value)
        if normalized is not None:
            return normalized
    return None


def _parse_single_vevent(component_ical_b64: str):
    try:
        component_bytes = base64.b64decode(component_ical_b64)
    except Exception:
        return None
    payload = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + component_bytes + b"\r\nEND:VCALENDAR\r\n"
    try:
        calendar = Calendar.from_ical(payload)
    except Exception:
        return None
    for component in calendar.walk():
        if getattr(component, "name", "") == "VEVENT":
            return component
    return None


def _normalize_ical_datetime(value: object) -> datetime | None:
    candidate = getattr(value, "dt", value)
    if isinstance(candidate, datetime):
        if candidate.tzinfo is None:
            return candidate.replace(tzinfo=timezone.utc)
        return candidate.astimezone(timezone.utc)
    return None


def _normalize_ical_date(value: object) -> date | None:
    candidate = getattr(value, "dt", value)
    if isinstance(candidate, datetime):
        return None
    if isinstance(candidate, date):
        return candidate
    return None


def _resolve_timezone(timezone_name: str | None) -> ZoneInfo:
    candidate = timezone_name or "UTC"
    try:
        return ZoneInfo(candidate)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


__all__ = [
    "SourceTermWindow",
    "SourceTermWindowConfigError",
    "calendar_component_in_window",
    "datetime_to_local_date",
    "message_internal_date_in_window",
    "normalize_term_window_config",
    "parse_iso_datetime",
    "parse_source_term_window",
    "parse_term_window_config",
    "semantic_due_date_in_window",
    "source_timezone_name",
]
