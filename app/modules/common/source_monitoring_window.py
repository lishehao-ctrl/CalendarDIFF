from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from icalendar import Calendar
from pydantic import BaseModel, Field, ValidationError, model_validator


class SourceMonitoringWindowConfigError(ValueError):
    pass


class SourceMonitoringWindowModel(BaseModel):
    monitor_since: date = Field()

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_model(self) -> "SourceMonitoringWindowModel":
        return self


@dataclass(frozen=True)
class SourceMonitoringWindow:
    monitor_since: date

    def to_config_json(self) -> dict[str, str]:
        return {"monitor_since": self.monitor_since.isoformat()}

    def contains_local_date(self, value: date | None) -> bool:
        return value is not None and value >= self.monitor_since

    def contains_datetime(self, value: datetime | None, *, timezone_name: str | None) -> bool:
        local_date = datetime_to_local_date(value, timezone_name=timezone_name)
        return self.contains_local_date(local_date)

    def is_expired(self, *, now: datetime, timezone_name: str | None) -> bool:
        del now, timezone_name
        return False

    def has_started(self, *, now: datetime, timezone_name: str | None) -> bool:
        local_date = datetime_to_local_date(now, timezone_name=timezone_name)
        return local_date is not None and local_date >= self.monitor_since

    def monitor_start_at_utc(self, *, timezone_name: str | None) -> datetime:
        zone = _resolve_timezone(timezone_name)
        local_start = datetime.combine(self.monitor_since, time.min, tzinfo=zone)
        return local_start.astimezone(timezone.utc)

    def gmail_query_bounds(self, *, timezone_name: str | None) -> tuple[str, str]:
        start = self.monitor_since.strftime("%Y/%m/%d")
        today_local = datetime_to_local_date(datetime.now(timezone.utc), timezone_name=timezone_name) or datetime.now(timezone.utc).date()
        end_exclusive = (today_local + timedelta(days=1)).strftime("%Y/%m/%d")
        return start, end_exclusive


MONITORING_WINDOW_KEYS = ("monitor_since",)
MONITORING_REQUIRED_KEYS = ("monitor_since",)
LEGACY_TERM_KEYS = ("term_key", "term_from", "term_to")
DEFAULT_MONITOR_LOOKBACK_DAYS = 90


def normalize_monitoring_window_config(
    *,
    config: dict[str, Any],
    required: bool,
    default_if_missing: bool = False,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    normalized = dict(config)
    window = parse_monitoring_window_config(normalized, required=False)
    if window is None:
        if required and not default_if_missing:
            raise SourceMonitoringWindowConfigError("config must include monitor_since")
        if default_if_missing:
            normalized.update(_default_monitoring_window(timezone_name=timezone_name).to_config_json())
        return normalized
    for key in LEGACY_TERM_KEYS:
        normalized.pop(key, None)
    normalized.update(window.to_config_json())
    return normalized


def parse_monitoring_window_config(config: Any, *, required: bool) -> SourceMonitoringWindow | None:
    if not isinstance(config, dict):
        if required:
            raise SourceMonitoringWindowConfigError("config must be an object")
        return None

    subset = {key: config.get(key) for key in MONITORING_WINDOW_KEYS if key in config}
    legacy_monitor_since = _legacy_monitor_since(config)
    if subset.get("monitor_since") in (None, "") and legacy_monitor_since is not None:
        subset["monitor_since"] = legacy_monitor_since.isoformat()

    present_required = [key for key in MONITORING_REQUIRED_KEYS if subset.get(key) not in (None, "")]
    if not present_required:
        if required:
            raise SourceMonitoringWindowConfigError("config must include monitor_since")
        return None
    try:
        model = SourceMonitoringWindowModel.model_validate(subset)
    except ValidationError as exc:
        raise SourceMonitoringWindowConfigError(_monitoring_window_validation_message(exc)) from exc
    return SourceMonitoringWindow(monitor_since=model.monitor_since)


def _monitoring_window_validation_message(exc: ValidationError) -> str:
    detail = exc.errors()[0] if exc.errors() else {}
    location = detail.get("loc") or ()
    message = detail.get("msg")
    field = location[-1] if location else None
    if isinstance(field, str) and field in MONITORING_WINDOW_KEYS:
        if isinstance(message, str) and message.strip():
            return f"invalid monitoring config: {field} ({message})"
        return f"invalid monitoring config: {field}"
    if isinstance(message, str) and message.strip():
        return f"invalid monitoring config: {message}"
    return "invalid monitoring config"


def parse_source_monitoring_window(source: Any, *, required: bool = False) -> SourceMonitoringWindow | None:
    source_config = getattr(source, "config", None)
    config_json = getattr(source_config, "config_json", None)
    return parse_monitoring_window_config(config_json, required=required)


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


def message_internal_date_in_window(*, internal_date: object, monitoring_window: SourceMonitoringWindow, timezone_name: str | None) -> bool:
    parsed = parse_iso_datetime(internal_date)
    return monitoring_window.contains_datetime(parsed, timezone_name=timezone_name)


def semantic_due_date_in_window(
    *,
    semantic_payload: dict[str, Any] | None,
    fallback_datetime: datetime | None,
    monitoring_window: SourceMonitoringWindow,
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
                return monitoring_window.contains_local_date(due_date_value)
    return monitoring_window.contains_datetime(fallback_datetime, timezone_name=timezone_name)


def calendar_component_in_window(
    *,
    component_ical_b64: object,
    monitoring_window: SourceMonitoringWindow,
    timezone_name: str | None,
) -> bool:
    if not isinstance(component_ical_b64, str) or not component_ical_b64.strip():
        return True
    component_datetime = extract_calendar_component_datetime(component_ical_b64)
    if component_datetime is not None:
        return monitoring_window.contains_datetime(component_datetime, timezone_name=timezone_name)
    component_date = extract_calendar_component_date(component_ical_b64)
    if component_date is not None:
        return monitoring_window.contains_local_date(component_date)
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


def _legacy_monitor_since(config: dict[str, Any]) -> date | None:
    raw = config.get("term_from")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


def _default_monitoring_window(*, timezone_name: str | None) -> SourceMonitoringWindow:
    local_today = datetime_to_local_date(datetime.now(timezone.utc), timezone_name=timezone_name) or datetime.now(timezone.utc).date()
    return SourceMonitoringWindow(monitor_since=local_today - timedelta(days=DEFAULT_MONITOR_LOOKBACK_DAYS))


__all__ = [
    "SourceMonitoringWindow",
    "SourceMonitoringWindowConfigError",
    "calendar_component_in_window",
    "datetime_to_local_date",
    "message_internal_date_in_window",
    "normalize_monitoring_window_config",
    "parse_iso_datetime",
    "parse_monitoring_window_config",
    "parse_source_monitoring_window",
    "semantic_due_date_in_window",
    "source_timezone_name",
]
