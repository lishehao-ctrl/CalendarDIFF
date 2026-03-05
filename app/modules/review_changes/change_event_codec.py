from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.review import Event


def parse_after_json(event_uid: str, payload: dict) -> dict | None:
    del event_uid
    start_raw = payload.get("start_at_utc")
    end_raw = payload.get("end_at_utc")
    title_raw = payload.get("title")
    course_label_raw = payload.get("course_label")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        return None
    start_at = parse_iso_datetime(start_raw)
    end_at = parse_iso_datetime(end_raw)
    if start_at is None or end_at is None or end_at <= start_at:
        return None
    title = title_raw.strip()[:512] if isinstance(title_raw, str) and title_raw.strip() else "Untitled"
    course_label = (
        course_label_raw.strip()[:64]
        if isinstance(course_label_raw, str) and course_label_raw.strip()
        else "Unknown"
    )
    return {
        "title": title,
        "course_label": course_label,
        "start_at_utc": start_at,
        "end_at_utc": end_at,
    }


def parse_iso_datetime(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def event_json_equivalent(before_json: dict, after_json: dict) -> bool:
    return (
        str(before_json.get("title") or "") == str(after_json.get("title") or "")
        and str(before_json.get("course_label") or "") == str(after_json.get("course_label") or "")
        and str(before_json.get("start_at_utc") or "") == str(after_json.get("start_at_utc") or "")
        and str(before_json.get("end_at_utc") or "") == str(after_json.get("end_at_utc") or "")
    )


def safe_delta_seconds(*, before_json: dict, after_json: dict) -> int | None:
    before_raw = before_json.get("start_at_utc")
    after_raw = after_json.get("start_at_utc")
    if not isinstance(before_raw, str) or not isinstance(after_raw, str):
        return None
    before = parse_iso_datetime(before_raw)
    after = parse_iso_datetime(after_raw)
    if before is None or after is None:
        return None
    return int((after - before).total_seconds())


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def event_row_to_json(event: Event) -> dict:
    return {
        "uid": event.uid,
        "title": event.title,
        "course_label": event.course_label,
        "start_at_utc": as_utc(event.start_at_utc).isoformat(),
        "end_at_utc": as_utc(event.end_at_utc).isoformat(),
    }


__all__ = [
    "event_json_equivalent",
    "event_row_to_json",
    "parse_after_json",
    "parse_iso_datetime",
    "safe_delta_seconds",
]
