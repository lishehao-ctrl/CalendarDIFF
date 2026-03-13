from __future__ import annotations

<<<<<<< ours
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.modules.review_changes.change_event_codec import parse_iso_datetime
=======
from datetime import date

from app.modules.core_ingest.semantic_event_service import normalize_semantic_event, semantic_event_with_patch
>>>>>>> theirs
from app.modules.review_changes.canonical_edit_errors import CanonicalEditValidationError


def build_candidate_after(
    *,
<<<<<<< ours
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
        raise CanonicalEditValidationError("patch.due_at must not be blank")
    local_tz = resolve_timezone_name(timezone_name)
    if "T" not in raw:
        try:
            due_date = date.fromisoformat(raw)
        except ValueError as exc:
            raise CanonicalEditValidationError("patch.due_at must be valid date or datetime") from exc
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
        raise CanonicalEditValidationError("patch.due_at must be valid date or datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(timezone.utc)


def resolve_timezone_name(value: str | None) -> ZoneInfo:
    normalized = (value or "").strip() or "UTC"
    try:
        return ZoneInfo(normalized)
    except Exception:
        return ZoneInfo("UTC")
=======
    entity_uid: str,
    base_payload: dict,
    patch: dict,
) -> dict:
    normalized_base = normalize_semantic_event({**base_payload, "uid": entity_uid})
    next_payload = dict(normalized_base)
    if "event_name" in patch:
        next_payload["event_name"] = coalesce_patch_text(
            patch.get("event_name"),
            fallback=str(normalized_base.get("event_name") or "Untitled"),
            max_len=512,
        )
    for field in ("course_dept", "course_number", "course_suffix", "course_quarter", "course_year2"):
        if field in patch and patch.get(field) is not None:
            next_payload[field] = patch.get(field)
    if "due_date" in patch:
        due_date_value = patch.get("due_date")
        if isinstance(due_date_value, date):
            next_payload["due_date"] = due_date_value.isoformat()
        elif isinstance(due_date_value, str) and due_date_value.strip():
            next_payload["due_date"] = due_date_value.strip()
        else:
            raise CanonicalEditValidationError("patch.due_date must be a valid date")
    if "due_time" in patch:
        next_payload["due_time"] = patch.get("due_time")
    if "time_precision" in patch and patch.get("time_precision") is not None:
        next_payload["time_precision"] = patch.get("time_precision")
    candidate = semantic_event_with_patch(normalized_base, next_payload)
    if candidate.get("time_precision") == "date_only":
        candidate["due_time"] = None
    if not candidate.get("due_date"):
        raise CanonicalEditValidationError("edited semantic payload must include due_date")
    if not isinstance(candidate.get("event_name"), str) or not str(candidate.get("event_name")).strip():
        raise CanonicalEditValidationError("edited semantic payload must include event_name")
    candidate["uid"] = entity_uid
    return candidate
>>>>>>> theirs


def coalesce_patch_text(value: str | None, *, fallback: str, max_len: int) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped[:max_len]
    fallback_clean = fallback.strip()
    if fallback_clean:
        return fallback_clean[:max_len]
    return "Unknown"[:max_len]


def edit_payload_from_event_json(payload: dict) -> dict:
<<<<<<< ours
    start_raw = payload.get("start_at_utc")
    end_raw = payload.get("end_at_utc")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        raise CanonicalEditValidationError("event payload missing start/end timestamps")
    start_at = parse_iso_datetime(start_raw)
    end_at = parse_iso_datetime(end_raw)
    if start_at is None or end_at is None:
        raise CanonicalEditValidationError("event payload contains invalid timestamps")
    uid = payload.get("uid")
    title = payload.get("title")
    course_label = payload.get("course_label")
    if not isinstance(uid, str) or not uid.strip():
        raise CanonicalEditValidationError("event payload missing uid")
    return {
        "uid": uid.strip(),
        "title": str(title or "Untitled")[:512],
        "course_label": str(course_label or "Unknown")[:64],
        "start_at_utc": start_at,
        "end_at_utc": end_at,
    }
=======
    normalized = normalize_semantic_event(payload)
    if not isinstance(normalized.get("uid"), str) or not normalized.get("uid"):
        raise CanonicalEditValidationError("event payload missing uid")
    if not isinstance(normalized.get("event_name"), str) or not normalized.get("event_name"):
        raise CanonicalEditValidationError("event payload missing event_name")
    if not normalized.get("due_date"):
        raise CanonicalEditValidationError("event payload missing valid semantic due fields")
    return normalized
>>>>>>> theirs


__all__ = [
    "build_candidate_after",
    "edit_payload_from_event_json",
]
