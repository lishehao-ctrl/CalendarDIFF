from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.modules.ingestion.llm_parsers.contracts import LlmParseError, ParserContext, ParserOutput
from app.modules.ingestion.llm_parsers.gmail_parser_extractors import extract_atomic_segment, extract_directive_segment
from app.modules.ingestion.llm_parsers.gmail_parser_planner import plan_gmail_segments
from app.modules.ingestion.llm_parsers.gmail_parser_records import build_atomic_record, build_directive_record
from app.modules.llm_gateway import invoke_llm_json


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

    planner, planner_model_hint = plan_gmail_segments(
        db=db,
        context=context,
        source_message_id=source_message_id,
        source_subject=source_subject,
        source_snippet=source_snippet,
        source_body_text=source_body_text,
        source_from_header=source_from_header,
        source_thread_id=source_thread_id,
        source_internal_date=source_internal_date,
        invoke_json=invoke_llm_json,
    )

    atomic_segments = [segment for segment in planner.segment_array if segment.segment_type_hint == "atomic"]
    base_message_id = source_message_id or planner.message_id or f"gmail-{context.source_id}"
    records: list[dict] = []
    segment_model_hints: list[str] = []

    for segment in atomic_segments:
        extraction, extraction_model_hint = extract_atomic_segment(
            db=db,
            context=context,
            source_message_id=base_message_id,
            source_subject=source_subject,
            source_from_header=source_from_header,
            source_thread_id=source_thread_id,
            source_internal_date=source_internal_date,
            segment=segment,
            invoke_json=invoke_llm_json,
        )
        if isinstance(extraction_model_hint, str) and extraction_model_hint.strip():
            segment_model_hints.append(extraction_model_hint.strip())
        records.append(
            build_atomic_record(
                base_message_id=base_message_id,
                source_subject=source_subject,
                source_snippet=source_snippet,
                source_from_header=source_from_header,
                source_thread_id=source_thread_id,
                source_internal_date=source_internal_date,
                segment=segment,
                atomic_segment_count=len(atomic_segments),
                extraction=extraction,
            )
        )

    directive_segments = [segment for segment in planner.segment_array if segment.segment_type_hint == "directive"]
    for segment in directive_segments:
        directive, directive_model_hint = extract_directive_segment(
            db=db,
            context=context,
            source_message_id=base_message_id,
            source_subject=source_subject,
            source_from_header=source_from_header,
            source_thread_id=source_thread_id,
            source_internal_date=source_internal_date,
            segment=segment,
            invoke_json=invoke_llm_json,
        )
        if isinstance(directive_model_hint, str) and directive_model_hint.strip():
            segment_model_hints.append(directive_model_hint.strip())
        records.append(
            build_directive_record(
                base_message_id=base_message_id,
                source_subject=source_subject,
                source_snippet=source_snippet,
                source_from_header=source_from_header,
                source_thread_id=source_thread_id,
                source_internal_date=source_internal_date,
                segment=segment,
                directive=directive,
            )
        )

    return ParserOutput(
        records=records,
        parser_name=parser_name,
        parser_version="mainline",
        model_hint=(segment_model_hints[0] if segment_model_hints else planner_model_hint or "unknown_model"),
    )


__all__ = ["parse_gmail_payload", "invoke_llm_json"]
