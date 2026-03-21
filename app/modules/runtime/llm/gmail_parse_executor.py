from __future__ import annotations

from app.core.config import get_settings
from app.modules.runtime.connectors.llm_parsers import LlmParseError, ParserContext


_GMAIL_PARSE_MAX_WORKERS = 6


def gmail_parse_worker_count(message_count: int) -> int:
    if message_count <= 1:
        return 1
    settings = get_settings()
    configured = max(1, int(getattr(settings, "llm_worker_concurrency", 1)))
    return max(1, min(message_count, configured, _GMAIL_PARSE_MAX_WORKERS))


def parse_single_gmail_message_impl(
    *,
    session_factory,
    redis_client,
    stream_key: str,
    source_id: int,
    provider: str,
    request_id: str,
    payload_item: dict,
    load_cached_gmail_parse_records_fn,
    store_cached_gmail_parse_records_fn,
    store_non_retryable_gmail_parse_skip_fn,
    increment_parse_metric_counter_fn,
    parse_gmail_payload_fn,
    invoke_parser_with_limit_fn,
    attach_parser_metadata_fn,
) -> list[dict]:
    with session_factory() as db:
        cached_records = load_cached_gmail_parse_records_fn(
            db=db,
            source_id=source_id,
            payload_item=payload_item,
        )
        if cached_records is not None:
            increment_parse_metric_counter_fn(redis_client, metric_name="gmail_parse_cache_hit")
            return cached_records

        context = ParserContext(
            source_id=source_id,
            provider=provider,
            source_kind="email",
            request_id=request_id,
        )

        def _parse_gmail_item() -> object:
            return parse_gmail_payload_fn(db=db, payload=payload_item, context=context)

        try:
            parser_output = invoke_parser_with_limit_fn(
                redis_client=redis_client,
                stream_key=stream_key,
                parse_call=_parse_gmail_item,
            )
        except LlmParseError as exc:
            if exc.retryable:
                raise
            store_non_retryable_gmail_parse_skip_fn(
                db=db,
                source_id=source_id,
                payload_item=payload_item,
                error_code=exc.code,
            )
            increment_parse_metric_counter_fn(
                redis_client,
                metric_name="gmail_messages_skipped_non_retryable_parse_error",
            )
            return []
        records = attach_parser_metadata_fn(records=parser_output.records, parser_output=parser_output)
        store_cached_gmail_parse_records_fn(
            db=db,
            source_id=source_id,
            payload_item=payload_item,
            records=records,
            error_code=None,
        )
        return records


__all__ = [
    "gmail_parse_worker_count",
    "parse_single_gmail_message_impl",
]
