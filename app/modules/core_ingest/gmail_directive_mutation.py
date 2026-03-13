from __future__ import annotations

from datetime import date, timedelta

_WEEKDAY_TO_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def apply_directive_mutation(*, before_payload: dict, mutation: dict) -> dict | None:
    if not isinstance(before_payload.get("due_date"), str):
        return None

    move_weekday = mutation.get("move_weekday")
    set_due_date = mutation.get("set_due_date")

    if isinstance(move_weekday, str) and move_weekday.strip():
        weekday_index = _WEEKDAY_TO_INDEX.get(move_weekday.strip().lower())
        if weekday_index is None:
            return None
        current_due_date = _parse_iso_date(before_payload.get("due_date"))
        if current_due_date is None:
            return None
        delta_days = (weekday_index - current_due_date.weekday()) % 7
        if delta_days == 0:
            delta_days = 7
        next_due_date = current_due_date + timedelta(days=delta_days)
        after_payload = dict(before_payload)
        after_payload["due_date"] = next_due_date.isoformat()
        if str(after_payload.get("time_precision") or "datetime") == "date_only":
            after_payload["due_time"] = None
        return after_payload

    parsed_set_due_date = _parse_iso_date(set_due_date)
    if parsed_set_due_date is None:
        return None
    after_payload = dict(before_payload)
    after_payload["due_date"] = parsed_set_due_date.isoformat()
    if str(after_payload.get("time_precision") or "datetime") == "date_only":
        after_payload["due_time"] = None
    return after_payload


def _parse_iso_date(raw: object) -> date | None:
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        return None


__all__ = ["apply_directive_mutation"]
