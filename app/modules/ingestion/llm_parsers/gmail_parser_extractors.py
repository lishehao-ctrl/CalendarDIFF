from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.ingestion.llm_parsers.contracts import ParserContext
from app.modules.ingestion.llm_parsers.gmail_parser_llm import LlmInvokeCallable, invoke_schema_validated
from app.modules.ingestion.llm_parsers.schemas import (
    GmailAtomicSegmentExtractionResponse,
    GmailDirectiveExtractionResponse,
    GmailPlannerSegment,
)
from app.modules.llm_gateway import LlmInvokeRequest


def extract_atomic_segment(
    *,
    db: Session,
    context: ParserContext,
    source_message_id: str,
    source_subject: str,
    source_from_header: str | None,
    source_thread_id: str | None,
    source_internal_date: str | None,
    segment: GmailPlannerSegment,
    invoke_json: LlmInvokeCallable,
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
    return invoke_schema_validated(
        db=db,
        context=context,
        invoke_request=invoke_request,
        response_model=GmailAtomicSegmentExtractionResponse,
        stage_label="gmail_segment_atomic_extract",
        invoke_json=invoke_json,
    )


def extract_directive_segment(
    *,
    db: Session,
    context: ParserContext,
    source_message_id: str,
    source_subject: str,
    source_from_header: str | None,
    source_thread_id: str | None,
    source_internal_date: str | None,
    segment: GmailPlannerSegment,
    invoke_json: LlmInvokeCallable,
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
    return invoke_schema_validated(
        db=db,
        context=context,
        invoke_request=invoke_request,
        response_model=GmailDirectiveExtractionResponse,
        stage_label="gmail_segment_directive_extract",
        invoke_json=invoke_json,
    )


__all__ = ["extract_atomic_segment", "extract_directive_segment"]
