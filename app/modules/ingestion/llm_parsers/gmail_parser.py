from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.modules.common.payload_schemas import SourceFacts
from app.modules.core_ingest.semantic_event_service import normalize_semantic_event
from app.modules.ingestion.llm_parsers.contracts import LlmParseError, ParserContext, ParserOutput
from app.modules.ingestion.llm_parsers.schemas import (
    GmailAtomicSegmentExtractionResponse,
    GmailDirectiveExtractionResponse,
    GmailPlannerResponse,
    GmailPlannerSegment,
)
from app.modules.llm_gateway import (
    LLM_FORMAT_MAX_ATTEMPTS,
    LlmGatewayError,
    LlmInvokeRequest,
    invoke_llm_json,
)

GMAIL_SCHEMA_INVALID_CODE = "parse_llm_gmail_schema_invalid"
GMAIL_UPSTREAM_ERROR_CODE = "parse_llm_gmail_upstream_error"
logger = logging.getLogger(__name__)


def parse_gmail_payload(*, db: Session, payload: dict, context: ParserContext) -> ParserOutput:
    parser_name = "gmail_llm"
    serialized_payload = json.dumps(payload, ensure_ascii=True)
    if not serialized_payload:
        raise LlmParseError(
            code="parse_llm_empty_output",
            message="gmail payload is empty",
            retryable=False,
            provider=context.provider,
            parser_version="mainline",
        )

    source_message_id = payload.get("message_id") if isinstance(payload.get("message_id"), str) else None
    source_subject = payload.get("subject") if isinstance(payload.get("subject"), str) else "Untitled"
    source_snippet = payload.get("snippet") if isinstance(payload.get("snippet"), str) else None
    source_body_text = payload.get("body_text") if isinstance(payload.get("body_text"), str) else None
    source_from_header = payload.get("from_header") if isinstance(payload.get("from_header"), str) else None
    source_thread_id = payload.get("thread_id") if isinstance(payload.get("thread_id"), str) else None
    source_internal_date = payload.get("internal_date") if isinstance(payload.get("internal_date"), str) else None

    planner, planner_model_hint = _plan_gmail_segments(
        db=db,
        context=context,
        source_message_id=source_message_id,
        source_subject=source_subject,
        source_snippet=source_snippet,
        source_body_text=source_body_text,
        source_from_header=source_from_header,
        source_thread_id=source_thread_id,
        source_internal_date=source_internal_date,
    )
    atomic_segments = [segment for segment in planner.segment_array if segment.segment_type_hint == "atomic"]
    base_message_id = source_message_id or planner.message_id or f"gmail-{context.source_id}"
    records: list[dict] = []
    segment_model_hints: list[str] = []
    for segment in atomic_segments:
        extraction, extraction_model_hint = _extract_atomic_segment(
            db=db,
            context=context,
            source_message_id=base_message_id,
            source_subject=source_subject,
            source_from_header=source_from_header,
            source_thread_id=source_thread_id,
            source_internal_date=source_internal_date,
            segment=segment,
        )
        if isinstance(extraction_model_hint, str) and extraction_model_hint.strip():
            segment_model_hints.append(extraction_model_hint.strip())
        message_id = _segment_message_id(
            base_message_id=base_message_id,
            segment_index=segment.segment_index,
            atomic_segment_count=len(atomic_segments),
        )
        semantic_event_draft = normalize_semantic_event(
            extraction.semantic_event_draft.model_dump(mode="json"),
            fallback_due_raw=source_internal_date,
        )
        due_start, due_end = _due_window_from_semantic(semantic_event_draft)
        confidence = float(semantic_event_draft.get("confidence") or 0.0)
        records.append(
            {
                "record_type": "gmail.message.extracted",
                "payload": {
                    "message_id": message_id,
                    "source_facts": SourceFacts.model_validate(
                        {
                            "external_event_id": message_id,
                            "source_title": source_subject[:512] if isinstance(source_subject, str) else "Untitled",
                            "source_summary": source_snippet,
                            "source_dtstart_utc": due_start,
                            "source_dtend_utc": due_end,
                            "time_anchor_confidence": confidence,
                            "from_header": source_from_header,
                            "thread_id": source_thread_id,
                            "internal_date": source_internal_date,
                        }
                    ).model_dump(mode="json"),
                    "semantic_event_draft": semantic_event_draft,
                    "link_signals": extraction.link_signals.model_dump(),
                },
            }
        )
    directive_segments = [segment for segment in planner.segment_array if segment.segment_type_hint == "directive"]
    for segment in directive_segments:
        directive, directive_model_hint = _extract_directive_segment(
            db=db,
            context=context,
            source_message_id=base_message_id,
            source_subject=source_subject,
            source_from_header=source_from_header,
            source_thread_id=source_thread_id,
            source_internal_date=source_internal_date,
            segment=segment,
        )
        if isinstance(directive_model_hint, str) and directive_model_hint.strip():
            segment_model_hints.append(directive_model_hint.strip())
        directive_external_event_id = _directive_external_event_id(
            base_message_id=base_message_id,
            segment_index=segment.segment_index,
        )
        records.append(
            {
                "record_type": "gmail.directive.extracted",
                "payload": {
                    "message_id": base_message_id,
                    "source_facts": SourceFacts.model_validate(
                        {
                            "external_event_id": directive_external_event_id,
                            "source_title": source_subject[:512] if isinstance(source_subject, str) else "Untitled",
                            "source_summary": segment.snippet or source_snippet,
                            "from_header": source_from_header,
                            "thread_id": source_thread_id,
                            "internal_date": source_internal_date,
                        }
                    ).model_dump(mode="json"),
                    "segment_index": segment.segment_index,
                    "segment_anchor": segment.anchor,
                    "segment_snippet": segment.snippet,
                    "directive": directive.model_dump(mode="json"),
                },
            }
        )

    return ParserOutput(
        records=records,
        parser_name=parser_name,
        parser_version="mainline",
        model_hint=(segment_model_hints[0] if segment_model_hints else planner_model_hint or "unknown_model"),
    )


def _plan_gmail_segments(
    *,
    db: Session,
    context: ParserContext,
    source_message_id: str | None,
    source_subject: str,
    source_snippet: str | None,
    source_body_text: str | None,
    source_from_header: str | None,
    source_thread_id: str | None,
    source_internal_date: str | None,
) -> tuple[GmailPlannerResponse, str | None]:
    invoke_request = LlmInvokeRequest(
        task_name="gmail_message_segment_plan",
        system_prompt=(
            "You are pass-1 planner for Gmail deadline parsing. "
            "Classify message text into extraction segments. "
            'Return JSON: {"message_id":string|null,"mode":string,"segment_array":[{"segment_index":number,'
            '"anchor":string|null,"snippet":string|null,"segment_type_hint":"atomic"|"directive"|"unknown"}]}. '
            "Use segment_type_hint=atomic for independent deadline-change statements. "
            "Use directive when the text is instruction-like/meta without direct event extraction. "
            "Use unknown when classification is uncertain."
        ),
        user_payload={
            "source_id": context.source_id,
            "provider": context.provider,
            "source_kind": context.source_kind,
            "message": {
                "message_id": source_message_id,
                "subject": source_subject,
                "snippet": source_snippet,
                "body_text": source_body_text,
                "from_header": source_from_header,
                "thread_id": source_thread_id,
                "internal_date": source_internal_date,
            },
        },
        output_schema_name="GmailPlannerResponse",
        output_schema_json=GmailPlannerResponse.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
    )
    return _invoke_schema_validated(
        db=db,
        context=context,
        invoke_request=invoke_request,
        response_model=GmailPlannerResponse,
        stage_label="gmail_message_segment_plan",
    )


def _extract_atomic_segment(
    *,
    db: Session,
    context: ParserContext,
    source_message_id: str,
    source_subject: str,
    source_from_header: str | None,
    source_thread_id: str | None,
    source_internal_date: str | None,
    segment: GmailPlannerSegment,
) -> tuple[GmailAtomicSegmentExtractionResponse, str | None]:
    invoke_request = LlmInvokeRequest(
        task_name="gmail_segment_atomic_extract",
        system_prompt=(
            "You are pass-2 extractor for one Gmail segment. "
            "Use only the provided segment snippet plus minimal message metadata. "
            'Return JSON: {"semantic_event_draft":{"course_dept":string|null,"course_number":number|null,'
            '"course_suffix":string|null,"course_quarter":"WI"|"SP"|"SU"|"FA"|null,"course_year2":number|null,'
            '"raw_type":string|null,"event_name":string|null,"ordinal":number|null,'
            '"due_date":string|null,"due_time":string|null,"time_precision":"date_only"|"datetime"|null,'
            '"confidence":number,"evidence":string},'
            '"link_signals":{"keywords":["exam"|"midterm"|"final"],"exam_sequence":number|null,'
            '"location_text":string|null,"instructor_hint":string|null}}. '
            "Do not output directive-only or non-event instructions."
        ),
        user_payload={
            "source_id": context.source_id,
            "provider": context.provider,
            "source_kind": context.source_kind,
            "message_meta": {
                "message_id": source_message_id,
                "subject": source_subject,
                "from_header": source_from_header,
                "thread_id": source_thread_id,
                "internal_date": source_internal_date,
            },
            "segment": {
                "segment_index": segment.segment_index,
                "anchor": segment.anchor,
                "snippet": segment.snippet,
                "segment_type_hint": segment.segment_type_hint,
            },
        },
        output_schema_name="GmailAtomicSegmentExtractionResponse",
        output_schema_json=GmailAtomicSegmentExtractionResponse.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
    )
    return _invoke_schema_validated(
        db=db,
        context=context,
        invoke_request=invoke_request,
        response_model=GmailAtomicSegmentExtractionResponse,
        stage_label="gmail_segment_atomic_extract",
    )


def _extract_directive_segment(
    *,
    db: Session,
    context: ParserContext,
    source_message_id: str,
    source_subject: str,
    source_from_header: str | None,
    source_thread_id: str | None,
    source_internal_date: str | None,
    segment: GmailPlannerSegment,
) -> tuple[GmailDirectiveExtractionResponse, str | None]:
    invoke_request = LlmInvokeRequest(
        task_name="gmail_segment_directive_extract",
        system_prompt=(
            "You are pass-2 extractor for one Gmail directive segment. "
            "Use only provided segment text and minimal message metadata. "
            'Return JSON with schema: {"selector":{"course_dept":string|null,"course_number":number|null,'
            '"course_suffix":string|null,"course_quarter":"WI"|"SP"|"SU"|"FA"|null,"course_year2":number|null,'
            '"family_hint":string|null,"raw_type_hint":string|null,'
            '"scope_mode":"all_matching"|"ordinal_list"|"ordinal_range","ordinal_list":[number],'
            '"ordinal_range_start":number|null,"ordinal_range_end":number|null,'
            '"current_due_weekday":"monday"|"tuesday"|"wednesday"|"thursday"|"friday"|"saturday"|"sunday"|null,'
            '"applies_to_future_only":boolean},'
            '"mutation":{"move_weekday":"monday"|"tuesday"|"wednesday"|"thursday"|"friday"|"saturday"|"sunday"|null,'
            '"set_due_date":string|null},'
            '"confidence":number,"evidence":string}. '
            "Mutation must set exactly one of move_weekday or set_due_date."
        ),
        user_payload={
            "source_id": context.source_id,
            "provider": context.provider,
            "source_kind": context.source_kind,
            "message_meta": {
                "message_id": source_message_id,
                "subject": source_subject,
                "from_header": source_from_header,
                "thread_id": source_thread_id,
                "internal_date": source_internal_date,
            },
            "segment": {
                "segment_index": segment.segment_index,
                "anchor": segment.anchor,
                "snippet": segment.snippet,
                "segment_type_hint": segment.segment_type_hint,
            },
        },
        output_schema_name="GmailDirectiveExtractionResponse",
        output_schema_json=GmailDirectiveExtractionResponse.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
    )
    return _invoke_schema_validated(
        db=db,
        context=context,
        invoke_request=invoke_request,
        response_model=GmailDirectiveExtractionResponse,
        stage_label="gmail_segment_directive_extract",
    )


def _invoke_schema_validated(
    *,
    db: Session,
    context: ParserContext,
    invoke_request: LlmInvokeRequest,
    response_model,
    stage_label: str,
) -> tuple[object, str | None]:
    parsed = None
    invoke_result = None
    for attempt in range(1, LLM_FORMAT_MAX_ATTEMPTS + 1):
        try:
            invoke_result = invoke_llm_json(db, invoke_request=invoke_request)
        except LlmGatewayError as exc:
            raise _map_llm_error(exc, provider=context.provider) from exc

        try:
            parsed = response_model.model_validate(invoke_result.json_object)
            break
        except ValidationError as exc:
            if attempt < LLM_FORMAT_MAX_ATTEMPTS:
                logger.warning(
                    "gmail_parser.format_retry request_id=%s source_id=%s task_name=%s error_code=%s attempt=%s/%s",
                    context.request_id or "-",
                    context.source_id,
                    stage_label,
                    GMAIL_SCHEMA_INVALID_CODE,
                    attempt,
                    LLM_FORMAT_MAX_ATTEMPTS,
                )
                continue
            logger.warning(
                "gmail_parser.format_retry_exhausted request_id=%s source_id=%s task_name=%s error_code=%s attempt=%s/%s",
                context.request_id or "-",
                context.source_id,
                stage_label,
                GMAIL_SCHEMA_INVALID_CODE,
                attempt,
                LLM_FORMAT_MAX_ATTEMPTS,
            )
            raise LlmParseError(
                code=GMAIL_SCHEMA_INVALID_CODE,
                message=f"gmail llm schema invalid ({stage_label}): {exc.errors()}",
                retryable=False,
                provider=context.provider,
                parser_version="mainline",
            ) from exc

    if parsed is None or invoke_result is None:
        raise LlmParseError(
            code=GMAIL_SCHEMA_INVALID_CODE,
            message=f"gmail llm parser returned no valid payload after retries ({stage_label})",
            retryable=False,
            provider=context.provider,
            parser_version="mainline",
        )
    model_hint = invoke_result.model if isinstance(invoke_result.model, str) and invoke_result.model.strip() else None
    return parsed, model_hint


def _segment_message_id(*, base_message_id: str, segment_index: int, atomic_segment_count: int) -> str:
    if atomic_segment_count <= 1:
        return base_message_id
    return f"{base_message_id}#seg-{segment_index}"


def _directive_external_event_id(*, base_message_id: str, segment_index: int) -> str:
    return f"{base_message_id}#directive-seg-{segment_index}"


def _due_window_from_semantic(semantic_parse: dict) -> tuple[str | None, str | None]:
    due_date_raw = semantic_parse.get("due_date")
    if not isinstance(due_date_raw, str) or not due_date_raw:
        return None, None
    try:
        due_date_value = date.fromisoformat(due_date_raw)
    except ValueError:
        return None, None
    due_time_raw = semantic_parse.get("due_time")
    time_precision = str(semantic_parse.get("time_precision") or "datetime")
    if time_precision == "date_only" or not isinstance(due_time_raw, str) or not due_time_raw:
        start_at = datetime(due_date_value.year, due_date_value.month, due_date_value.day, 23, 59, tzinfo=timezone.utc)
    else:
        try:
            due_time_value = time.fromisoformat(due_time_raw)
        except ValueError:
            return None, None
        start_at = datetime.combine(due_date_value, due_time_value, tzinfo=timezone.utc)
    return start_at.isoformat(), (start_at + timedelta(hours=1)).isoformat()


def _map_llm_error(exc: LlmGatewayError, *, provider: str) -> LlmParseError:
    if exc.code == "parse_llm_timeout":
        return LlmParseError(
            code="parse_llm_timeout",
            message=str(exc),
            retryable=True,
            provider=provider,
            parser_version="mainline",
        )
    if exc.code == "parse_llm_empty_output":
        return LlmParseError(
            code="parse_llm_empty_output",
            message=str(exc),
            retryable=False,
            provider=provider,
            parser_version="mainline",
        )
    if exc.code == "parse_llm_schema_invalid":
        return LlmParseError(
            code=GMAIL_SCHEMA_INVALID_CODE,
            message=str(exc),
            retryable=False,
            provider=provider,
            parser_version="mainline",
        )
    if exc.code == "parse_llm_upstream_error":
        return LlmParseError(
            code=GMAIL_UPSTREAM_ERROR_CODE,
            message=str(exc),
            retryable=exc.retryable,
            provider=provider,
            parser_version="mainline",
        )
    return LlmParseError(
        code=exc.code,
        message=str(exc),
        retryable=exc.retryable,
        provider=provider,
        parser_version="mainline",
    )
