from __future__ import annotations

import json

from app.core.security import decrypt_secret
from app.db.models.input import InputSource
from app.modules.sources.provider_sources import CANVAS_ICS_DISPLAY_NAME, CANVAS_ICS_SOURCE_KEY
from app.modules.sources.source_runtime_state import SourceRuntimeStateProjection


def serialize_source(
    source: InputSource,
    *,
    runtime_state: SourceRuntimeStateProjection | None = None,
    active_request_id: str | None = None,
    sync_progress: dict | None = None,
    operator_guidance: dict | None = None,
    source_product_phase: str | None = None,
    source_recovery: dict | None = None,
) -> dict:
    oauth_connection_status = None
    oauth_account_email = None
    source_key = source.source_key
    display_name = source.display_name

    if source.provider == "gmail":
        oauth_connection_status = "not_connected"
        oauth_account_email = _extract_gmail_account_email(source)
        if oauth_account_email:
            oauth_connection_status = "connected"
    if source.provider == "ics":
        source_key = CANVAS_ICS_SOURCE_KEY
        display_name = CANVAS_ICS_DISPLAY_NAME

    return {
        "source_id": source.id,
        "user_id": source.user_id,
        "source_kind": source.source_kind.value,
        "provider": source.provider,
        "source_key": source_key,
        "display_name": display_name,
        "is_active": source.is_active,
        "poll_interval_seconds": source.poll_interval_seconds,
        "last_polled_at": source.last_polled_at,
        "next_poll_at": source.next_poll_at,
        "last_error_code": source.last_error_code,
        "last_error_message": source.last_error_message,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
        "config": source.config.config_json if source.config is not None else {},
        "oauth_connection_status": oauth_connection_status,
        "oauth_account_email": oauth_account_email,
        "lifecycle_state": runtime_state.lifecycle_state if runtime_state is not None else "active",
        "sync_state": runtime_state.sync_state if runtime_state is not None else "idle",
        "config_state": runtime_state.config_state if runtime_state is not None else "stable",
        "runtime_state": runtime_state.runtime_state if runtime_state is not None else "active",
        "active_request_id": active_request_id,
        "sync_progress": sync_progress,
        "operator_guidance": operator_guidance,
        "source_product_phase": source_product_phase,
        "source_recovery": source_recovery,
    }


def _extract_gmail_account_email(source: InputSource) -> str | None:
    if source.secrets is None or not source.secrets.encrypted_payload:
        return None
    try:
        payload = json.loads(decrypt_secret(source.secrets.encrypted_payload))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    account_email = payload.get("account_email")
    if isinstance(account_email, str) and account_email.strip():
        return account_email.strip()
    return None


__all__ = ["serialize_source"]
