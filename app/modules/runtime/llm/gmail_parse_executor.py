from __future__ import annotations

from app.core.config import get_settings
from app.modules.runtime.connectors.llm_parsers import LlmParseError, ParserContext


def gmail_parse_worker_count(message_count: int) -> int:
    if message_count <= 1:
        return 1
    settings = get_settings()
    configured = max(1, int(getattr(settings, "llm_worker_concurrency", 1)))
    gmail_parse_cap = max(1, int(getattr(settings, "gmail_parse_max_workers", configured)))
    return max(1, min(message_count, configured, gmail_parse_cap))


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
    load_cached_gmail_purpose_mode_fn,
    store_cached_gmail_parse_records_fn,
    store_cached_gmail_purpose_mode_fn,
    store_non_retryable_gmail_parse_skip_fn,
    classify_gmail_message_fast_path_fn,
    increment_parse_metric_counter_fn,
    record_gmail_parse_summary_stat_fn,
    parse_gmail_payload_fn,
    invoke_parser_with_limit_fn,
    attach_parser_metadata_fn,
) -> list[dict]:
    with session_factory() as db:
        record_gmail_parse_summary_stat_fn("message_count")
        cached_records = load_cached_gmail_parse_records_fn(
            db=db,
            source_id=source_id,
            payload_item=payload_item,
        )
        if cached_records is not None:
            increment_parse_metric_counter_fn(redis_client, metric_name="gmail_parse_cache_hit")
            record_gmail_parse_summary_stat_fn("final_parse_cache_hit_count")
            return cached_records

        purpose_cache = load_cached_gmail_purpose_mode_fn(
            db=db,
            source_id=source_id,
            payload_item=payload_item,
        )
        payload_for_parse = dict(payload_item)
        if purpose_cache is not None:
            record_gmail_parse_summary_stat_fn("purpose_cache_hit_count")
            record_gmail_parse_summary_stat_fn(f"purpose_cache_hit_{purpose_cache.mode}_count")
            if purpose_cache.hit_type == "content_hash":
                record_gmail_parse_summary_stat_fn("purpose_cache_shared_content_hit_count")
            elif purpose_cache.hit_type == "fingerprint":
                record_gmail_parse_summary_stat_fn("purpose_cache_fingerprint_hit_count")
            record_gmail_parse_summary_stat_fn(f"purpose_{purpose_cache.mode}_count")
            if purpose_cache.mode == "unknown":
                store_cached_gmail_parse_records_fn(
                    db=db,
                    source_id=source_id,
                    payload_item=payload_item,
                    records=[],
                    error_code=None,
                )
                return []
            payload_for_parse["_gmail_purpose_mode_hint"] = purpose_cache.to_hint_payload()
        else:
            fast_path = classify_gmail_message_fast_path_fn(payload_item=payload_item)
            if fast_path is not None:
                store_cached_gmail_purpose_mode_fn(
                    db=db,
                    source_id=source_id,
                    payload_item=payload_item,
                    mode=fast_path.mode,
                    evidence=fast_path.evidence,
                    reason_code=fast_path.reason_code,
                    decision_source="fast_path",
                    provider_id=None,
                    model=None,
                    protocol=None,
                )
                store_cached_gmail_parse_records_fn(
                    db=db,
                    source_id=source_id,
                    payload_item=payload_item,
                    records=[],
                    error_code=None,
                )
                record_gmail_parse_summary_stat_fn("deterministic_fast_path_unknown_count")
                record_gmail_parse_summary_stat_fn("purpose_unknown_count")
                return []

        context = ParserContext(
            source_id=source_id,
            provider=provider,
            source_kind="email",
            request_id=request_id,
        )

        def _parse_gmail_item() -> object:
            return parse_gmail_payload_fn(db=db, payload=payload_for_parse, context=context)

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
        parser_metadata = getattr(parser_output, "metadata", {}) if isinstance(getattr(parser_output, "metadata", {}), dict) else {}
        purpose_metadata = parser_metadata.get("gmail_purpose") if isinstance(parser_metadata.get("gmail_purpose"), dict) else None
        if purpose_metadata is not None:
            mode = str(purpose_metadata.get("mode") or "").strip().lower()
            if mode in {"unknown", "atomic", "directive"}:
                record_gmail_parse_summary_stat_fn(f"purpose_{mode}_count")
                if str(purpose_metadata.get("decision_source") or "") == "llm":
                    record_gmail_parse_summary_stat_fn("llm_purpose_classify_call_count")
                    store_cached_gmail_purpose_mode_fn(
                        db=db,
                        source_id=source_id,
                        payload_item=payload_item,
                        mode=mode,
                        evidence=purpose_metadata.get("evidence") if isinstance(purpose_metadata.get("evidence"), str) else None,
                        reason_code=purpose_metadata.get("reason_code") if isinstance(purpose_metadata.get("reason_code"), str) else None,
                        decision_source="llm",
                        provider_id=purpose_metadata.get("provider_id") if isinstance(purpose_metadata.get("provider_id"), str) else None,
                        model=purpose_metadata.get("model") if isinstance(purpose_metadata.get("model"), str) else None,
                        protocol=purpose_metadata.get("protocol") if isinstance(purpose_metadata.get("protocol"), str) else None,
                    )
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
