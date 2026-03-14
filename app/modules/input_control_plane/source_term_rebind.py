from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource, InputSourceConfig, SyncRequest, SyncRequestStatus
from app.modules.common.source_term_window import (
    SourceTermWindow,
    normalize_term_window_config,
    parse_source_term_window,
    parse_term_window_config,
    source_timezone_name,
)
from app.modules.input_control_plane.source_term_rescope import apply_source_term_rescope, term_window_changed

PENDING_TERM_REBIND_KEY = "pending_term_rebind"
INFLIGHT_SYNC_STATUSES = (SyncRequestStatus.QUEUED, SyncRequestStatus.RUNNING)
TERMINAL_SYNC_STATUSES = {SyncRequestStatus.SUCCEEDED, SyncRequestStatus.FAILED}


def has_active_sync_requests(*, db: Session, source_id: int) -> bool:
    row = db.scalar(
        select(SyncRequest.id)
        .where(
            SyncRequest.source_id == source_id,
            SyncRequest.status.in_(INFLIGHT_SYNC_STATUSES),
        )
        .limit(1)
    )
    return row is not None


def has_pending_term_rebind(source: InputSource) -> bool:
    return pending_term_rebind_payload(source) is not None


def pending_term_rebind_payload(source: InputSource) -> dict[str, Any] | None:
    config_json = _source_config_json(source)
    pending = config_json.get(PENDING_TERM_REBIND_KEY)
    if isinstance(pending, dict):
        return dict(pending)
    return None


def queue_pending_term_rebind(
    *,
    source: InputSource,
    requested_config: dict[str, Any],
    requested_at: datetime,
    requested_by_user_id: int | None,
) -> None:
    next_config = dict(requested_config)
    next_config.pop(PENDING_TERM_REBIND_KEY, None)
    requested_window = parse_term_window_config(next_config, required=True)
    config = _get_or_create_source_config(source)
    config_json = dict(config.config_json or {})
    config_json[PENDING_TERM_REBIND_KEY] = _build_pending_term_rebind_payload(
        requested_window=requested_window,
        requested_config=next_config,
        requested_at=requested_at,
        requested_by_user_id=requested_by_user_id,
    )
    config.config_json = config_json


def apply_pending_term_rebind_if_terminal(
    *,
    db: Session,
    source: InputSource,
    terminal_status: SyncRequestStatus,
    applied_at: datetime,
) -> bool:
    if terminal_status not in TERMINAL_SYNC_STATUSES:
        return False
    pending = pending_term_rebind_payload(source)
    if pending is None:
        return False

    config = _get_or_create_source_config(source)
    active_config = dict(config.config_json or {})
    previous_term_window = parse_source_term_window(source, required=False)

    requested_config_raw = pending.get("requested_config")
    if isinstance(requested_config_raw, dict):
        next_config = dict(requested_config_raw)
    else:
        next_config = dict(active_config)
        for key in ("term_key", "term_from", "term_to"):
            value = pending.get(key)
            if isinstance(value, str) and value.strip():
                next_config[key] = value.strip()
    next_config.pop(PENDING_TERM_REBIND_KEY, None)

    if source.provider in {"gmail", "ics"}:
        normalized_next_config = normalize_term_window_config(config=next_config, required=True)
    else:
        normalized_next_config = normalize_term_window_config(config=next_config, required=False)
    config.config_json = normalized_next_config

    next_term_window = parse_term_window_config(normalized_next_config, required=False)
    timezone_name = source_timezone_name(source)
    if source.is_active:
        if next_term_window is not None and next_term_window.is_expired(now=applied_at, timezone_name=timezone_name):
            source.is_active = False
            source.next_poll_at = None
        elif next_term_window is not None:
            source.next_poll_at = max(applied_at, next_term_window.monitor_start_at_utc(timezone_name=timezone_name))
        else:
            source.next_poll_at = source.next_poll_at or applied_at

    should_rescope = term_window_changed(previous=previous_term_window, current=next_term_window)
    if should_rescope and next_term_window is not None:
        apply_source_term_rescope(
            db=db,
            source=source,
            term_window=next_term_window,
            applied_at=applied_at,
        )
    return True


def _source_config_json(source: InputSource) -> dict[str, Any]:
    config = getattr(source, "config", None)
    config_json = getattr(config, "config_json", None)
    if isinstance(config_json, dict):
        return config_json
    return {}


def _get_or_create_source_config(source: InputSource) -> InputSourceConfig:
    config = source.config
    if config is not None:
        return config
    config = InputSourceConfig(source_id=source.id, schema_version=1, config_json={})
    source.config = config
    return config


def _build_pending_term_rebind_payload(
    *,
    requested_window: SourceTermWindow,
    requested_config: dict[str, Any],
    requested_at: datetime,
    requested_by_user_id: int | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "term_key": requested_window.term_key,
        "term_from": requested_window.term_from.isoformat(),
        "term_to": requested_window.term_to.isoformat(),
        "requested_config": dict(requested_config),
        "requested_at": requested_at.isoformat(),
    }
    if isinstance(requested_by_user_id, int):
        payload["requested_by_user_id"] = requested_by_user_id
    return payload


__all__ = [
    "PENDING_TERM_REBIND_KEY",
    "apply_pending_term_rebind_if_terminal",
    "has_active_sync_requests",
    "has_pending_term_rebind",
    "pending_term_rebind_payload",
    "queue_pending_term_rebind",
]
