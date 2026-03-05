from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.modules.review_changes.change_event_codec import parse_iso_datetime
from app.modules.review_changes.manual_correction_errors import ManualCorrectionValidationError


def build_candidate_after(
    *,
    event_uid: str,
    base_snapshot: dict,
    due_at: str,
    title: str | None,
    course_label: str | None,
    timezone_name: str,
) -> dict:
    due_at_utc = normalize_due_at_with_user_timezone(due_at, timezone_name=timezone_name)
    next_end_at = due_at_utc + timedelta(hours=1)
    next_title = coalesce_patch_text(title, fallback=str(base_snapshot.get("title") or "Untitled"), max_len=512)
    next_course_label = coalesce_patch_text(
        course_label,
        fallback=str(base_snapshot.get("course_label") or "Unknown"),
        max_len=64,
    )
    return {
        "uid": event_uid,
        "title": next_title,
        "course_label": next_course_label,
        "start_at_utc": due_at_utc.isoformat(),
        "end_at_utc": next_end_at.isoformat(),
    }


def normalize_due_at_with_user_timezone(value: str, *, timezone_name: str) -> datetime:
    raw = value.strip() if isinstance(value, str) else ""
    if not raw:
        raise ManualCorrectionValidationError("patch.due_at must not be blank")
    local_tz = resolve_timezone_name(timezone_name)
    if "T" not in raw:
        try:
            due_date = date.fromisoformat(raw)
        except ValueError as exc:
            raise ManualCorrectionValidationError("patch.due_at must be valid date or datetime") from exc
        local_due = datetime(
            due_date.year,
            due_date.month,
            due_date.day,
            23,
            59,
            0,
            tzinfo=local_tz,
        )
        return local_due.astimezone(timezone.utc)

    normalized = raw[:-1] + "+00:00" if raw.lower().endswith("z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ManualCorrectionValidationError("patch.due_at must be valid date or datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(timezone.utc)


def resolve_timezone_name(value: str | None) -> ZoneInfo:
    normalized = (value or "").strip() or "UTC"
    try:
        return ZoneInfo(normalized)
    except Exception:
        return ZoneInfo("UTC")


def coalesce_patch_text(value: str | None, *, fallback: str, max_len: int) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped[:max_len]
    fallback_clean = fallback.strip()
    if fallback_clean:
        return fallback_clean[:max_len]
    return "Unknown"[:max_len]


def manual_payload_from_event_json(payload: dict) -> dict:
    start_raw = payload.get("start_at_utc")
    end_raw = payload.get("end_at_utc")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        raise ManualCorrectionValidationError("event payload missing start/end timestamps")
    start_at = parse_iso_datetime(start_raw)
    end_at = parse_iso_datetime(end_raw)
    if start_at is None or end_at is None:
        raise ManualCorrectionValidationError("event payload contains invalid timestamps")
    uid = payload.get("uid")
    title = payload.get("title")
    course_label = payload.get("course_label")
    if not isinstance(uid, str) or not uid.strip():
        raise ManualCorrectionValidationError("event payload missing uid")
    return {
        "uid": uid.strip(),
        "title": str(title or "Untitled")[:512],
        "course_label": str(course_label or "Unknown")[:64],
        "start_at_utc": start_at,
        "end_at_utc": end_at,
    }


__all__ = [
    "build_candidate_after",
    "manual_payload_from_event_json",
]
