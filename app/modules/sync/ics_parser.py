from __future__ import annotations

from datetime import date, datetime, time, timezone

from icalendar import Calendar

from app.modules.sync.types import RawICSEvent


class ICSParser:
    def parse(self, content: bytes) -> list[RawICSEvent]:
        calendar = Calendar.from_ical(content)
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
