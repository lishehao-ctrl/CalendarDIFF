from __future__ import annotations

from typing import Any


LEGACY_TOP_LEVEL_KEYS = frozenset(
    {
        "uid",
        "title",
        "start_at",
        "end_at",
        "course_label",
        "raw_confidence",
        "subject",
        "event_type",
        "due_at",
        "confidence",
        "raw_extract",
    }
)


class PayloadContractError(RuntimeError):
    pass


def validate_calendar_payload_v3(*, payload: dict[str, Any], record_index: int) -> None:
    _ensure_no_legacy_top_level(payload=payload, record_index=record_index, record_type="calendar.event.extracted")
    source_canonical = _require_dict(
        payload,
        key="source_canonical",
        record_index=record_index,
        record_type="calendar.event.extracted",
    )
    enrichment = _require_dict(
        payload,
        key="enrichment",
        record_index=record_index,
        record_type="calendar.event.extracted",
    )
    _require_non_empty_str(
        source_canonical,
        key="external_event_id",
        record_index=record_index,
        record_type="calendar.event.extracted",
    )
    _require_non_empty_str(
        source_canonical,
        key="source_title",
        record_index=record_index,
        record_type="calendar.event.extracted",
    )
    _require_non_empty_str(
        source_canonical,
        key="source_dtstart_utc",
        record_index=record_index,
        record_type="calendar.event.extracted",
    )
    _require_non_empty_str(
        source_canonical,
        key="source_dtend_utc",
        record_index=record_index,
        record_type="calendar.event.extracted",
    )
    _require_dict(
        enrichment,
        key="course_parse",
        record_index=record_index,
        record_type="calendar.event.extracted",
    )
    _require_dict(
        enrichment,
        key="work_item_parse",
        record_index=record_index,
        record_type="calendar.event.extracted",
    )
    _require_dict(
        enrichment,
        key="event_parts",
        record_index=record_index,
        record_type="calendar.event.extracted",
    )
    _require_dict(
        enrichment,
        key="link_signals",
        record_index=record_index,
        record_type="calendar.event.extracted",
    )
    schema_version = enrichment.get("payload_schema_version")
    if schema_version != "obs_v3":
        raise PayloadContractError(
            _invalid_payload_message(
                record_type="calendar.event.extracted",
                record_index=record_index,
                detail="missing enrichment.payload_schema_version=obs_v3",
            )
        )


def validate_gmail_payload_v3(*, payload: dict[str, Any], record_index: int) -> None:
    _ensure_no_legacy_top_level(payload=payload, record_index=record_index, record_type="gmail.message.extracted")
    message_id = payload.get("message_id")
    if not isinstance(message_id, str) or not message_id.strip():
        raise PayloadContractError(
            _invalid_payload_message(
                record_type="gmail.message.extracted",
                record_index=record_index,
                detail="missing payload.message_id",
            )
        )
    source_canonical = _require_dict(
        payload,
        key="source_canonical",
        record_index=record_index,
        record_type="gmail.message.extracted",
    )
    enrichment = _require_dict(
        payload,
        key="enrichment",
        record_index=record_index,
        record_type="gmail.message.extracted",
    )
    _require_non_empty_str(
        source_canonical,
        key="external_event_id",
        record_index=record_index,
        record_type="gmail.message.extracted",
    )
    _require_non_empty_str(
        source_canonical,
        key="source_title",
        record_index=record_index,
        record_type="gmail.message.extracted",
    )
    _require_dict(
        enrichment,
        key="course_parse",
        record_index=record_index,
        record_type="gmail.message.extracted",
    )
    _require_dict(
        enrichment,
        key="work_item_parse",
        record_index=record_index,
        record_type="gmail.message.extracted",
    )
    _require_dict(
        enrichment,
        key="event_parts",
        record_index=record_index,
        record_type="gmail.message.extracted",
    )
    _require_dict(
        enrichment,
        key="link_signals",
        record_index=record_index,
        record_type="gmail.message.extracted",
    )
    schema_version = enrichment.get("payload_schema_version")
    if schema_version != "obs_v3":
        raise PayloadContractError(
            _invalid_payload_message(
                record_type="gmail.message.extracted",
                record_index=record_index,
                detail="missing enrichment.payload_schema_version=obs_v3",
            )
        )


def _ensure_no_legacy_top_level(*, payload: dict[str, Any], record_index: int, record_type: str) -> None:
    found = sorted(key for key in LEGACY_TOP_LEVEL_KEYS if key in payload)
    if found:
        raise PayloadContractError(
            _invalid_payload_message(
                record_type=record_type,
                record_index=record_index,
                detail=f"legacy keys are not allowed: {','.join(found)}",
            )
        )


def _require_dict(
    payload: dict[str, Any],
    *,
    key: str,
    record_index: int,
    record_type: str,
) -> dict[str, Any]:
    value = payload.get(key)
    if isinstance(value, dict):
        return value
    raise PayloadContractError(
        _invalid_payload_message(
            record_type=record_type,
            record_index=record_index,
            detail=f"missing object payload.{key}",
        )
    )


def _require_non_empty_str(
    payload: dict[str, Any],
    *,
    key: str,
    record_index: int,
    record_type: str,
) -> str:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise PayloadContractError(
        _invalid_payload_message(
            record_type=record_type,
            record_index=record_index,
            detail=f"missing string payload.{key}",
        )
    )


def _invalid_payload_message(*, record_type: str, record_index: int, detail: str) -> str:
    return f"core_ingest_payload_invalid record_type={record_type} index={record_index}: {detail}"
