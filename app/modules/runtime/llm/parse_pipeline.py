from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed

import redis
from sqlalchemy.orm import Session, sessionmaker

from app.db.models.runtime import ConnectorResultStatus
from app.modules.runtime.connectors.llm_parsers import (
    LlmParseError,
    ParserContext,
    parse_calendar_content,
    parse_gmail_payload,
)
from app.modules.runtime.connectors.parser_records import attach_parser_metadata
from app.modules.runtime.llm.calendar_component_parse_executor import (
    CalendarChangedComponentInput,
    build_minimal_calendar_text,
    normalize_calendar_changed_component_input,
    parse_calendar_changed_component_with_llm_impl,
    parse_calendar_delta_with_llm_impl,
)
from app.modules.runtime.llm.calendar_parse_cache import (
    load_cached_calendar_component_records,
    store_cached_calendar_component_records,
    store_non_retryable_calendar_component_skip,
)
from app.modules.runtime.llm.gmail_parse_executor import (
    gmail_parse_worker_count,
    parse_single_gmail_message_impl,
)
from app.modules.runtime.llm.gmail_parse_cache import (
    load_cached_gmail_parse_records,
    store_cached_gmail_parse_records,
    store_non_retryable_gmail_parse_skip,
)
from app.modules.runtime.llm.parser_invocation import (
    RateLimitRejected,
    invoke_parser_with_limit_impl,
    is_rate_limited_llm_error_impl,
)
from app.modules.runtime.kernel.parse_task_queue import increment_parse_metric_counter


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
    if parse_kind not in {"gmail", "calendar", "calendar_delta"}:
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

    if parse_kind == "calendar_delta":
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

    message_items = [item for item in messages if isinstance(item, dict)]
    max_workers = _gmail_parse_worker_count(len(message_items))
    if max_workers <= 1 or len(message_items) <= 1:
        for item in message_items:
            records.extend(
                _parse_single_gmail_message(
                    session_factory=session_factory,
                    redis_client=redis_client,
                    stream_key=stream_key,
                    source_id=source_id,
                    provider=provider,
                    request_id=request_id,
                    payload_item=item,
                )
            )
    else:
        indexed_results: dict[int, list[dict]] = {}
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="gmail-parse") as pool:
            future_map = {
                pool.submit(
                    _parse_single_gmail_message,
                    session_factory=session_factory,
                    redis_client=redis_client,
                    stream_key=stream_key,
                    source_id=source_id,
                    provider=provider,
                    request_id=request_id,
                    payload_item=item,
                ): index
                for index, item in enumerate(message_items)
            }
            for future in as_completed(future_map):
                indexed_results[future_map[future]] = future.result()
        for index in sorted(indexed_results):
            records.extend(indexed_results[index])
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
    return parse_calendar_delta_with_llm_impl(
        redis_client=redis_client,
        stream_key=stream_key,
        parse_payload=parse_payload,
        provider=provider,
        request_id=request_id,
        source_id=source_id,
        session_factory=session_factory,
        parse_calendar_changed_component_with_llm_fn=parse_calendar_changed_component_with_llm,
    )


def _parse_single_gmail_message(
    *,
    session_factory: sessionmaker[Session],
    redis_client: redis.Redis,
    stream_key: str,
    source_id: int,
    provider: str,
    request_id: str,
    payload_item: dict,
) -> list[dict]:
    return parse_single_gmail_message_impl(
        session_factory=session_factory,
        redis_client=redis_client,
        stream_key=stream_key,
        source_id=source_id,
        provider=provider,
        request_id=request_id,
        payload_item=payload_item,
        load_cached_gmail_parse_records_fn=load_cached_gmail_parse_records,
        store_cached_gmail_parse_records_fn=store_cached_gmail_parse_records,
        store_non_retryable_gmail_parse_skip_fn=store_non_retryable_gmail_parse_skip,
        increment_parse_metric_counter_fn=increment_parse_metric_counter,
        parse_gmail_payload_fn=parse_gmail_payload,
        invoke_parser_with_limit_fn=invoke_parser_with_limit,
        attach_parser_metadata_fn=attach_parser_metadata,
    )


def invoke_parser_with_limit(*, redis_client: redis.Redis, stream_key: str, parse_call):
    return invoke_parser_with_limit_impl(
        redis_client=redis_client,
        stream_key=stream_key,
        parse_call=parse_call,
    )


def is_rate_limited_llm_error(exc: LlmParseError) -> bool:
    return is_rate_limited_llm_error_impl(exc)


def _gmail_parse_worker_count(message_count: int) -> int:
    return gmail_parse_worker_count(message_count)


def parse_calendar_changed_component_with_llm(
    *,
    db: Session,
    redis_client: redis.Redis,
    stream_key: str,
    provider: str,
    context: ParserContext,
    component: CalendarChangedComponentInput,
) -> list[dict]:
    return parse_calendar_changed_component_with_llm_impl(
        db=db,
        redis_client=redis_client,
        stream_key=stream_key,
        provider=provider,
        context=context,
        component=component,
        load_cached_calendar_component_records_fn=load_cached_calendar_component_records,
        store_cached_calendar_component_records_fn=store_cached_calendar_component_records,
        store_non_retryable_calendar_component_skip_fn=store_non_retryable_calendar_component_skip,
        increment_parse_metric_counter_fn=increment_parse_metric_counter,
        parse_calendar_content_fn=parse_calendar_content,
        invoke_parser_with_limit_fn=invoke_parser_with_limit,
        attach_parser_metadata_fn=attach_parser_metadata,
    )


__all__ = [
    "CalendarChangedComponentInput",
    "RateLimitRejected",
    "build_minimal_calendar_text",
    "normalize_calendar_changed_component_input",
    "parse_calendar_changed_component_with_llm",
    "invoke_parser_with_limit",
    "is_rate_limited_llm_error",
    "parse_calendar_delta_with_llm",
    "parse_with_llm",
]
