from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from app.db.models.input import SyncRequest, SyncRequestStage, SyncRequestStatus
from app.modules.runtime.kernel.retry_policy import truncate_error

_UNSET: Final = object()


def build_sync_progress_payload(
    *,
    phase: str,
    label: str,
    detail: str | None = None,
    current: int | None = None,
    total: int | None = None,
    percent: float | int | None = None,
    unit: str | None = None,
    updated_at: datetime | None = None,
) -> dict:
    normalized_current = _coerce_optional_int(current)
    normalized_total = _coerce_optional_int(total)
    normalized_percent = _coerce_optional_float(percent)
    if normalized_percent is None and normalized_current is not None and normalized_total not in {None, 0}:
        normalized_percent = round((normalized_current / normalized_total) * 100, 1)
    timestamp = updated_at or datetime.now(UTC)
    return {
        "phase": phase,
        "label": label,
        "detail": detail,
        "current": normalized_current,
        "total": normalized_total,
        "percent": normalized_percent,
        "unit": unit,
        "updated_at": _to_iso8601(timestamp),
    }


def set_sync_runtime_state(
    sync_request: SyncRequest,
    *,
    status: SyncRequestStatus | None | object = _UNSET,
    stage: SyncRequestStage | None | object = _UNSET,
    substage: str | None | object = _UNSET,
    progress: dict | None | object = _UNSET,
    error_code: str | None | object = _UNSET,
    error_message: str | None | object = _UNSET,
    when: datetime | None = None,
) -> None:
    changed = False
    updated_at = when or datetime.now(UTC)

    if status is not _UNSET and sync_request.status != status:
        sync_request.status = status
        changed = True
    if stage is not _UNSET and sync_request.stage != stage:
        sync_request.stage = stage
        changed = True
    if substage is not _UNSET and sync_request.substage != substage:
        sync_request.substage = substage
        changed = True
    if progress is not _UNSET:
        normalized_progress = _normalize_existing_progress(progress, updated_at=updated_at)
        if sync_request.progress_json != normalized_progress:
            sync_request.progress_json = normalized_progress
            changed = True
    if error_code is not _UNSET:
        normalized_error_code = error_code
        if sync_request.error_code != normalized_error_code:
            sync_request.error_code = normalized_error_code
            changed = True
    if error_message is not _UNSET:
        normalized_error_message = truncate_error(error_message) if isinstance(error_message, str) else error_message
        if sync_request.error_message != normalized_error_message:
            sync_request.error_message = normalized_error_message
            changed = True

    if changed:
        sync_request.stage_updated_at = updated_at


def clear_sync_runtime_progress(sync_request: SyncRequest, *, when: datetime | None = None) -> None:
    set_sync_runtime_state(sync_request, progress=None, when=when)


def _normalize_existing_progress(progress: dict | None | object, *, updated_at: datetime) -> dict | None:
    if progress is None:
        return None
    if not isinstance(progress, dict):
        return None
    raw_updated_at = progress.get("updated_at")
    normalized_updated_at = _parse_iso8601(raw_updated_at) if isinstance(raw_updated_at, str) else None
    return build_sync_progress_payload(
        phase=str(progress.get("phase") or "running"),
        label=str(progress.get("label") or "Running"),
        detail=str(progress.get("detail")) if progress.get("detail") is not None else None,
        current=_coerce_optional_int(progress.get("current")),
        total=_coerce_optional_int(progress.get("total")),
        percent=_coerce_optional_float(progress.get("percent")),
        unit=str(progress.get("unit")) if progress.get("unit") is not None else None,
        updated_at=normalized_updated_at or updated_at,
    )


def _coerce_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _coerce_optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _to_iso8601(value: datetime) -> str:
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.isoformat().replace("+00:00", "Z")


def _parse_iso8601(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


__all__ = [
    "build_sync_progress_payload",
    "clear_sync_runtime_progress",
    "set_sync_runtime_state",
]
