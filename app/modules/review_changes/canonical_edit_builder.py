from __future__ import annotations

from datetime import date, time

from app.modules.core_ingest.semantic_event_service import normalize_semantic_event, semantic_event_with_patch
from app.modules.review_changes.canonical_edit_errors import CanonicalEditValidationError


def build_candidate_after(
    *,
    entity_uid: str,
    base_payload: dict,
    patch: dict,
) -> dict:
    normalized_base = _normalize_or_raise({**base_payload, "uid": entity_uid})
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
            try:
                normalized_due_date = date.fromisoformat(due_date_value.strip())
            except ValueError as exc:
                raise CanonicalEditValidationError("patch.due_date must be a valid date") from exc
            next_payload["due_date"] = normalized_due_date.isoformat()
        else:
            raise CanonicalEditValidationError("patch.due_date must be a valid date")

    if "due_time" in patch:
        due_time_value = patch.get("due_time")
        if due_time_value is None:
            next_payload["due_time"] = None
        elif isinstance(due_time_value, time):
            next_payload["due_time"] = due_time_value.replace(tzinfo=None).isoformat()
        elif isinstance(due_time_value, str):
            cleaned_due_time = due_time_value.strip()
            if not cleaned_due_time:
                next_payload["due_time"] = None
            else:
                try:
                    normalized_due_time = time.fromisoformat(cleaned_due_time).replace(tzinfo=None)
                except ValueError as exc:
                    raise CanonicalEditValidationError("patch.due_time must be a valid time") from exc
                next_payload["due_time"] = normalized_due_time.isoformat()
        else:
            raise CanonicalEditValidationError("patch.due_time must be a valid time")

    if "time_precision" in patch and patch.get("time_precision") is not None:
        time_precision_value = patch.get("time_precision")
        if time_precision_value not in {"date_only", "datetime"}:
            raise CanonicalEditValidationError("patch.time_precision must be date_only or datetime")
        next_payload["time_precision"] = time_precision_value

    try:
        candidate = semantic_event_with_patch(normalized_base, next_payload)
    except Exception as exc:
        raise CanonicalEditValidationError("canonical edit produced invalid event payload") from exc

    if candidate.get("time_precision") == "date_only":
        candidate["due_time"] = None
    if not candidate.get("due_date"):
        raise CanonicalEditValidationError("edited semantic payload must include due_date")
    if not isinstance(candidate.get("event_name"), str) or not str(candidate.get("event_name")).strip():
        raise CanonicalEditValidationError("edited semantic payload must include event_name")
    candidate["uid"] = entity_uid
    return candidate


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
    normalized = _normalize_or_raise(payload)
    if not isinstance(normalized.get("uid"), str) or not normalized.get("uid"):
        raise CanonicalEditValidationError("event payload missing uid")
    if not isinstance(normalized.get("event_name"), str) or not normalized.get("event_name"):
        raise CanonicalEditValidationError("event payload missing event_name")
    if not normalized.get("due_date"):
        raise CanonicalEditValidationError("event payload missing valid semantic due fields")
    return normalized


def _normalize_or_raise(payload: object) -> dict:
    try:
        return normalize_semantic_event(payload)
    except Exception as exc:
        raise CanonicalEditValidationError("canonical edit produced invalid event payload") from exc


__all__ = [
    "build_candidate_after",
    "edit_payload_from_event_json",
]
