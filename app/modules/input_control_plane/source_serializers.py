from __future__ import annotations

from app.db.models import InputSource


def serialize_source(source: InputSource) -> dict:
    return {
        "source_id": source.id,
        "user_id": source.user_id,
        "source_kind": source.source_kind.value,
        "provider": source.provider,
        "source_key": source.source_key,
        "display_name": source.display_name,
        "is_active": source.is_active,
        "poll_interval_seconds": source.poll_interval_seconds,
        "last_polled_at": source.last_polled_at,
        "next_poll_at": source.next_poll_at,
        "last_error_code": source.last_error_code,
        "last_error_message": source.last_error_message,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
        "config": source.config.config_json if source.config is not None else {},
    }


__all__ = ["serialize_source"]
