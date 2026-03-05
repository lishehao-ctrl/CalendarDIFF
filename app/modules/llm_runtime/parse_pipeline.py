from __future__ import annotations

import base64
import time
from collections.abc import Callable

import redis
from sqlalchemy.orm import Session, sessionmaker

from app.db.models.ingestion import ConnectorResultStatus
from app.modules.ingestion.ics_delta import external_event_id_from_component_key
from app.modules.ingestion.llm_parsers import (
    LlmParseError,
    ParserContext,
    parse_calendar_content,
    parse_gmail_payload,
)
from app.modules.ingestion.parser_records import attach_parser_metadata
from app.modules.llm_runtime.limiter import acquire_global_permit
from app.modules.llm_runtime.queue import increment_metric_counter, record_latency_ms


class RateLimitRejected(RuntimeError):
    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def parse_with_llm(
    *,
    redis_client: redis.Redis,
    stream_key: str,
    source_id: int,
    provider_hint: str,
    parse_payload: dict,
    request_id: str,
) -> tuple[list[dict], ConnectorResultStatus]:
    parse_kind = str(parse_payload.get("kind") or "").strip().lower()
    if parse_kind not in {"gmail", "calendar", "calendar_delta_v1"}:
        raise LlmParseError(
            code="llm_parse_kind_invalid",
            message=f"unsupported llm parse kind: {parse_kind or '-'}",
            retryable=False,
            provider=provider_hint or "-",
            parser_version="mainline",
        )

    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    records: list[dict] = []
    provider = provider_hint or parse_kind

    if parse_kind == "calendar":
        content_b64 = parse_payload.get("content_b64")
        if not isinstance(content_b64, str) or not content_b64:
            raise LlmParseError(
                code="llm_calendar_payload_invalid",
                message="calendar parse payload missing content_b64",
                retryable=False,
                provider=provider,
                parser_version="mainline",
            )
        try:
            content = base64.b64decode(content_b64.encode("utf-8"), validate=True)
        except Exception as exc:
            raise LlmParseError(
                code="llm_calendar_payload_invalid",
                message=f"invalid calendar content_b64: {exc}",
                retryable=False,
                provider=provider,
                parser_version="mainline",
            ) from exc

        with session_factory() as db:
            context = ParserContext(
                source_id=source_id,
                provider=provider,
                source_kind="calendar",
                request_id=request_id,
            )
            parser_output = invoke_parser_with_limit(
                redis_client=redis_client,
                stream_key=stream_key,
                parse_call=lambda: parse_calendar_content(db=db, content=content, context=context),
            )
            records.extend(attach_parser_metadata(records=parser_output.records, parser_output=parser_output))
        return records, ConnectorResultStatus.CHANGED

    if parse_kind == "calendar_delta_v1":
        return parse_calendar_delta_with_llm(
            redis_client=redis_client,
            stream_key=stream_key,
            parse_payload=parse_payload,
            provider=provider,
            request_id=request_id,
            source_id=source_id,
            session_factory=session_factory,
        )

    messages = parse_payload.get("messages")
    if not isinstance(messages, list):
        raise LlmParseError(
            code="llm_gmail_payload_invalid",
            message="gmail parse payload missing messages list",
            retryable=False,
            provider=provider,
            parser_version="mainline",
        )

    with session_factory() as db:
        context = ParserContext(
            source_id=source_id,
            provider=provider,
            source_kind="email",
            request_id=request_id,
        )
        for item in messages:
            if not isinstance(item, dict):
                continue
            parser_output = invoke_parser_with_limit(
                redis_client=redis_client,
                stream_key=stream_key,
                parse_call=lambda item=item: parse_gmail_payload(db=db, payload=item, context=context),
            )
            records.extend(attach_parser_metadata(records=parser_output.records, parser_output=parser_output))
    status = ConnectorResultStatus.CHANGED if records else ConnectorResultStatus.NO_CHANGE
    return records, status


def parse_calendar_delta_with_llm(
    *,
    redis_client: redis.Redis,
    stream_key: str,
    parse_payload: dict,
    provider: str,
    request_id: str,
    source_id: int,
    session_factory: sessionmaker[Session],
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
            if not isinstance(item, dict):
                continue
            component_key_raw = item.get("component_key")
            component_ical_b64 = item.get("component_ical_b64")
            if not isinstance(component_key_raw, str) or not component_key_raw.strip():
                continue
            if not isinstance(component_ical_b64, str) or not component_ical_b64:
                continue
            component_key = component_key_raw.strip()
            external_event_id_raw = item.get("external_event_id")
            if isinstance(external_event_id_raw, str) and external_event_id_raw.strip():
                external_event_id = external_event_id_raw.strip()
            else:
                external_event_id = external_event_id_from_component_key(component_key)

            try:
                component_bytes = base64.b64decode(component_ical_b64.encode("utf-8"), validate=True)
            except Exception as exc:
                raise LlmParseError(
                    code="llm_calendar_delta_payload_invalid",
                    message=f"invalid calendar delta component_ical_b64: {exc}",
                    retryable=False,
                    provider=provider,
                    parser_version="mainline",
                ) from exc

            try:
                component_text = component_bytes.decode("utf-8")
            except Exception as exc:
                raise LlmParseError(
                    code="llm_calendar_delta_payload_invalid",
                    message=f"calendar delta component is not utf-8: {exc}",
                    retryable=False,
                    provider=provider,
                    parser_version="mainline",
                ) from exc

            calendar_text = build_minimal_calendar_text(component_text)
            parser_output = invoke_parser_with_limit(
                redis_client=redis_client,
                stream_key=stream_key,
                parse_call=lambda calendar_text=calendar_text: parse_calendar_content(
                    db=db,
                    content=calendar_text.encode("utf-8"),
                    context=context,
                ),
            )
            parsed_records = attach_parser_metadata(records=parser_output.records, parser_output=parser_output)
            for record in parsed_records:
                if not isinstance(record, dict) or record.get("record_type") != "calendar.event.extracted":
                    continue
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    continue
                payload["uid"] = external_event_id
                source_canonical = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else {}
                source_canonical["external_event_id"] = external_event_id
                source_canonical["component_key"] = component_key
                payload["source_canonical"] = source_canonical
                payload["component_key"] = component_key
            records.extend(parsed_records)

    status = ConnectorResultStatus.CHANGED if records else ConnectorResultStatus.NO_CHANGE
    return records, status


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


def invoke_parser_with_limit(*, redis_client: redis.Redis, stream_key: str, parse_call: Callable[[], object]):
    decision = acquire_global_permit(redis_client)
    if not decision.allowed:
        increment_metric_counter(redis_client, metric_name="limiter_rejects")
        increment_metric_counter(redis_client, metric_name="llm_calls_rate_limited")
        raise RateLimitRejected(reason=decision.reason)

    increment_metric_counter(redis_client, metric_name="llm_calls_total")
    started = time.perf_counter()
    try:
        result = parse_call()
        latency_ms = max(int((time.perf_counter() - started) * 1000), 0)
        record_latency_ms(redis_client, stream_key=stream_key, latency_ms=latency_ms)
        return result
    except LlmParseError as exc:
        latency_ms = max(int((time.perf_counter() - started) * 1000), 0)
        record_latency_ms(redis_client, stream_key=stream_key, latency_ms=latency_ms)
        if is_rate_limited_llm_error(exc):
            increment_metric_counter(redis_client, metric_name="llm_calls_rate_limited")
        raise
    except Exception:
        latency_ms = max(int((time.perf_counter() - started) * 1000), 0)
        record_latency_ms(redis_client, stream_key=stream_key, latency_ms=latency_ms)
        raise


def is_rate_limited_llm_error(exc: LlmParseError) -> bool:
    code = exc.code.lower()
    message = str(exc).lower()
    return "rate_limit" in code or "rate_limited" in code or "429" in message


__all__ = [
    "RateLimitRejected",
    "build_minimal_calendar_text",
    "invoke_parser_with_limit",
    "is_rate_limited_llm_error",
    "parse_calendar_delta_with_llm",
    "parse_with_llm",
]
