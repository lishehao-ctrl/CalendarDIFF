from __future__ import annotations

from datetime import date, datetime, time, timezone
from importlib import import_module

from app.modules.sync.types import RawICSEvent


class ICSParser:
    """Legacy ICS parser kept for archive/reference only."""

    def parse(self, content: bytes) -> list[RawICSEvent]:
        calendar_module = import_module("icalendar")
        calendar_cls = getattr(calendar_module, "Calendar")
        parse_calendar = getattr(calendar_cls, "from_ical")
        calendar = parse_calendar(content)
        events: list[RawICSEvent] = []

        for component in calendar.walk("VEVENT"):
            summary = str(component.get("summary", "")).strip() or "Untitled"
            description = str(component.get("description", "")).strip()
            uid_value = component.get("uid")
            uid = str(uid_value).strip() if uid_value else None

            dtstart_raw = component.decoded("dtstart")
            dtend_raw = component.decoded("dtend") if component.get("dtend") else dtstart_raw

            dtstart = _to_utc_datetime(dtstart_raw)
            dtend = _to_utc_datetime(dtend_raw)
            if dtend < dtstart:
                dtend = dtstart

            events.append(
                RawICSEvent(
                    uid=uid,
                    summary=summary,
                    description=description,
                    dtstart=dtstart,
                    dtend=dtend,
                )
            )

        return events


def _to_utc_datetime(value: datetime | date) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, time.min)
    else:  # pragma: no cover - parser contract guard
        raise TypeError(f"Unsupported datetime value: {type(value)!r}")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
