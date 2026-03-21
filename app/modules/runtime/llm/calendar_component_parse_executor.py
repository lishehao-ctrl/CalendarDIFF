from __future__ import annotations

import base64
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from app.db.models.runtime import ConnectorResultStatus
from app.modules.common.payload_schemas import SourceFacts
from app.modules.runtime.connectors.ics_delta import external_event_id_from_component_key
from app.modules.runtime.connectors.llm_parsers import LlmParseError, ParserContext


@dataclass(frozen=True)
class CalendarChangedComponentInput:
    component_key: str
    external_event_id: str
    component_ical_b64: str
    fingerprint: str | None = None


def build_minimal_calendar_text(component_ical_text: str) -> str:
    body = component_ical_text.strip()
    if "BEGIN:VEVENT" not in body or "END:VEVENT" not in body:
        raise LlmParseError(
            code="llm_calendar_delta_payload_invalid",
            message="calendar delta component missing VEVENT wrapper",
            retryable=False,
            provider="calendar",
            parser_version="mainline",
        )
    return "\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalendarDIFF//ICS Delta//EN",
            body,
            "END:VCALENDAR",
            "",
        ]
    )


def normalize_calendar_changed_component_input(item: dict) -> CalendarChangedComponentInput | None:
    if not isinstance(item, dict):
        return None
    component_key_raw = item.get("component_key")
    component_ical_b64 = item.get("component_ical_b64")
    if not isinstance(component_key_raw, str) or not component_key_raw.strip():
        return None
    if not isinstance(component_ical_b64, str) or not component_ical_b64:
        return None
    component_key = component_key_raw.strip()
    external_event_id_raw = item.get("external_event_id")
    if isinstance(external_event_id_raw, str) and external_event_id_raw.strip():
        external_event_id = external_event_id_raw.strip()
    else:
        external_event_id = external_event_id_from_component_key(component_key)
    fingerprint = item.get("fingerprint") if isinstance(item.get("fingerprint"), str) and item.get("fingerprint").strip() else None
    return CalendarChangedComponentInput(
        component_key=component_key,
        external_event_id=external_event_id,
        component_ical_b64=component_ical_b64,
        fingerprint=fingerprint,
    )


def parse_calendar_changed_component_with_llm_impl(
    *,
    db: Session,
    redis_client,
    stream_key: str,
    provider: str,
    context: ParserContext,
    component: CalendarChangedComponentInput,
    load_cached_calendar_component_records_fn,
    store_cached_calendar_component_records_fn,
    store_non_retryable_calendar_component_skip_fn,
    increment_parse_metric_counter_fn,
    parse_calendar_content_fn,
    invoke_parser_with_limit_fn,
    attach_parser_metadata_fn,
) -> list[dict]:
    cached_records = load_cached_calendar_component_records_fn(
        db=db,
        source_id=context.source_id,
        fingerprint=component.fingerprint,
    )
    if cached_records is not None:
        increment_parse_metric_counter_fn(redis_client, metric_name="calendar_component_parse_cache_hit")
        return cached_records

    try:
        component_bytes = base64.b64decode(component.component_ical_b64.encode("utf-8"), validate=True)
    except Exception as exc:
        parse_error = LlmParseError(
            code="llm_calendar_delta_payload_invalid",
            message=f"invalid calendar delta component_ical_b64: {exc}",
            retryable=False,
            provider=provider,
            parser_version="mainline",
        )
        store_non_retryable_calendar_component_skip_fn(
            db=db,
            source_id=context.source_id,
            fingerprint=component.fingerprint,
            error_code=parse_error.code,
        )
        raise parse_error from exc

    try:
        component_text = component_bytes.decode("utf-8")
    except Exception as exc:
        parse_error = LlmParseError(
            code="llm_calendar_delta_payload_invalid",
            message=f"calendar delta component is not utf-8: {exc}",
            retryable=False,
            provider=provider,
            parser_version="mainline",
        )
        store_non_retryable_calendar_component_skip_fn(
            db=db,
            source_id=context.source_id,
            fingerprint=component.fingerprint,
            error_code=parse_error.code,
        )
        raise parse_error from exc

    try:
        calendar_text = build_minimal_calendar_text(component_text)
    except LlmParseError as exc:
        if not exc.retryable:
            store_non_retryable_calendar_component_skip_fn(
                db=db,
                source_id=context.source_id,
                fingerprint=component.fingerprint,
                error_code=exc.code,
            )
        raise

    def _parse_calendar_item() -> object:
        return parse_calendar_content_fn(
            db=db,
            content=calendar_text.encode("utf-8"),
            context=context,
        )

    try:
        parser_output = invoke_parser_with_limit_fn(
            redis_client=redis_client,
            stream_key=stream_key,
            parse_call=_parse_calendar_item,
        )
    except LlmParseError as exc:
        if not exc.retryable:
            store_non_retryable_calendar_component_skip_fn(
                db=db,
                source_id=context.source_id,
                fingerprint=component.fingerprint,
                error_code=exc.code,
            )
        raise
    parsed_records = attach_parser_metadata_fn(records=parser_output.records, parser_output=parser_output)
    for record in parsed_records:
        if not isinstance(record, dict) or record.get("record_type") != "calendar.event.extracted":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        payload["raw_ics_component_b64"] = component.component_ical_b64
        source_facts_raw = payload.get("source_facts")
        source_facts = source_facts_raw if isinstance(source_facts_raw, dict) else {}
        payload["source_facts"] = SourceFacts.model_validate(
            {
                **source_facts,
                "external_event_id": component.external_event_id,
                "component_key": component.component_key,
            }
        ).model_dump(mode="json")
        payload["component_key"] = component.component_key
    store_cached_calendar_component_records_fn(
        db=db,
        source_id=context.source_id,
        fingerprint=component.fingerprint,
        records=parsed_records,
        error_code=None,
    )
    return parsed_records


def parse_calendar_delta_with_llm_impl(
    *,
    redis_client,
    stream_key: str,
    parse_payload: dict,
    provider: str,
    request_id: str,
    source_id: int,
    session_factory: sessionmaker[Session],
    parse_calendar_changed_component_with_llm_fn,
) -> tuple[list[dict], ConnectorResultStatus]:
    changed_components = parse_payload.get("changed_components")
    removed_component_keys = parse_payload.get("removed_component_keys")
    if not isinstance(changed_components, list):
        raise LlmParseError(
            code="llm_calendar_delta_payload_invalid",
            message="calendar delta payload missing changed_components list",
            retryable=False,
            provider=provider,
            parser_version="mainline",
        )
    if not isinstance(removed_component_keys, list):
        raise LlmParseError(
            code="llm_calendar_delta_payload_invalid",
            message="calendar delta payload missing removed_component_keys list",
            retryable=False,
            provider=provider,
            parser_version="mainline",
        )

    records: list[dict] = []
    for raw_key in removed_component_keys:
        if not isinstance(raw_key, str) or not raw_key.strip():
            continue
        component_key = raw_key.strip()
        records.append(
            {
                "record_type": "calendar.event.removed",
                "payload": {
                    "component_key": component_key,
                    "external_event_id": external_event_id_from_component_key(component_key),
                },
            }
        )

    if not changed_components:
        status = ConnectorResultStatus.CHANGED if records else ConnectorResultStatus.NO_CHANGE
        return records, status

    with session_factory() as db:
        context = ParserContext(
            source_id=source_id,
            provider=provider,
            source_kind="calendar",
            request_id=request_id,
        )
        for item in changed_components:
            normalized = normalize_calendar_changed_component_input(item)
            if normalized is None:
                continue
            parsed_records = parse_calendar_changed_component_with_llm_fn(
                db=db,
                redis_client=redis_client,
                stream_key=stream_key,
                provider=provider,
                context=context,
                component=normalized,
            )
            records.extend(parsed_records)

    status = ConnectorResultStatus.CHANGED if records else ConnectorResultStatus.NO_CHANGE
    return records, status


__all__ = [
    "CalendarChangedComponentInput",
    "build_minimal_calendar_text",
    "normalize_calendar_changed_component_input",
    "parse_calendar_changed_component_with_llm_impl",
    "parse_calendar_delta_with_llm_impl",
]
