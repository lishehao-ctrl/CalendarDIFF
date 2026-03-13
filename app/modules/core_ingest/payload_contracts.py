from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.modules.common.payload_schemas import LinkSignals, SemanticEventDraft, SourceFacts

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
        "enrichment",
    }
)


class PayloadContractError(RuntimeError):
    pass


def validate_calendar_payload(*, payload: dict[str, Any], record_index: int) -> None:
    _ensure_no_legacy_top_level(payload=payload, record_index=record_index, record_type="calendar.event.extracted")
    source_facts = _validate_source_facts(payload=payload, record_index=record_index, record_type="calendar.event.extracted")
    if not source_facts.source_dtstart_utc:
        raise PayloadContractError(
            _invalid_payload_message(
                record_type="calendar.event.extracted",
                record_index=record_index,
                detail="missing string payload.source_facts.source_dtstart_utc",
            )
        )
    if not source_facts.source_dtend_utc:
        raise PayloadContractError(
            _invalid_payload_message(
                record_type="calendar.event.extracted",
                record_index=record_index,
                detail="missing string payload.source_facts.source_dtend_utc",
            )
        )
    _validate_semantic_event_draft(payload=payload, record_index=record_index, record_type="calendar.event.extracted")
    _validate_link_signals(payload=payload, record_index=record_index, record_type="calendar.event.extracted")


def validate_gmail_payload(*, payload: dict[str, Any], record_index: int) -> None:
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
    _validate_source_facts(payload=payload, record_index=record_index, record_type="gmail.message.extracted")
    _validate_semantic_event_draft(payload=payload, record_index=record_index, record_type="gmail.message.extracted")
    _validate_link_signals(payload=payload, record_index=record_index, record_type="gmail.message.extracted")


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


def _require_dict(payload: dict[str, Any], *, key: str, record_index: int, record_type: str) -> dict[str, Any]:
    value = payload.get(key)
    if isinstance(value, dict):
        return value
    raise PayloadContractError(
        _invalid_payload_message(record_type=record_type, record_index=record_index, detail=f"missing object payload.{key}")
    )


def _require_non_empty_str(payload: dict[str, Any], *, key: str, record_index: int, record_type: str) -> str:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise PayloadContractError(
        _invalid_payload_message(record_type=record_type, record_index=record_index, detail=f"missing string payload.{key}")
    )


def _invalid_payload_message(*, record_type: str, record_index: int, detail: str) -> str:
    return f"core_ingest_payload_invalid record_type={record_type} index={record_index}: {detail}"


def _validate_source_facts(*, payload: dict[str, Any], record_index: int, record_type: str) -> SourceFacts:
    raw = _require_dict(payload, key="source_facts", record_index=record_index, record_type=record_type)
    try:
        return SourceFacts.model_validate(raw)
    except ValidationError as exc:
        raise PayloadContractError(
            _invalid_payload_message(record_type=record_type, record_index=record_index, detail=f"invalid payload.source_facts: {exc.errors()[0]['loc'][-1]}")
        ) from exc


def _validate_semantic_event_draft(*, payload: dict[str, Any], record_index: int, record_type: str) -> SemanticEventDraft:
    raw = _require_dict(payload, key="semantic_event_draft", record_index=record_index, record_type=record_type)
    try:
        return SemanticEventDraft.model_validate(raw)
    except ValidationError as exc:
        raise PayloadContractError(
            _invalid_payload_message(record_type=record_type, record_index=record_index, detail=f"invalid payload.semantic_event_draft: {exc.errors()[0]['loc'][-1]}")
        ) from exc


def _validate_link_signals(*, payload: dict[str, Any], record_index: int, record_type: str) -> LinkSignals:
    raw = _require_dict(payload, key="link_signals", record_index=record_index, record_type=record_type)
    try:
        return LinkSignals.model_validate(raw)
    except ValidationError as exc:
        raise PayloadContractError(
            _invalid_payload_message(record_type=record_type, record_index=record_index, detail=f"invalid payload.link_signals: {exc.errors()[0]['loc'][-1]}")
        ) from exc
