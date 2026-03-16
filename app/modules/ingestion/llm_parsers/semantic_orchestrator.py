from __future__ import annotations

from html import unescape
import logging
import re
from typing import Any, TypeVar, cast

from icalendar import Calendar
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.modules.common.payload_schemas import SourceFacts
from app.modules.core_ingest.semantic_event_service import normalize_semantic_event, split_due_parts
from app.modules.ingestion.ics_delta.fingerprint import build_component_key, build_external_event_id
from app.modules.ingestion.llm_parsers.contracts import LlmParseError, ParserContext, ParserOutput
from app.modules.ingestion.llm_parsers.gmail_parser_records import build_atomic_record, build_directive_record
from app.modules.ingestion.llm_parsers.schemas import (
    CalendarRelevanceResponse,
    CalendarSemanticEventClassification,
    GmailAtomicSegmentExtractionResponse,
    GmailDirectiveExtractionResponse,
    GmailPlannerSegment,
    GmailPurposeModeResponse,
)
from app.modules.llm_gateway import (
    LLM_FORMAT_MAX_ATTEMPTS,
    LlmGatewayError,
    LlmInvokeRequest,
    LlmInvokeResult,
    invoke_llm_json,
)

logger = logging.getLogger(__name__)

GMAIL_SCHEMA_INVALID_CODE = "parse_llm_gmail_schema_invalid"
GMAIL_UPSTREAM_ERROR_CODE = "parse_llm_gmail_upstream_error"
CALENDAR_SCHEMA_INVALID_CODE = "parse_llm_calendar_schema_invalid"
CALENDAR_UPSTREAM_ERROR_CODE = "parse_llm_calendar_upstream_error"

_HTML_BREAK_RE = re.compile(r"(?i)<(?:br|/p|/div|/li|/tr|/h[1-6])[^>]*>")
_HTML_TAG_RE = re.compile(r"(?s)<[^>]+>")
_HTML_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1>")
_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINE_RE = re.compile(r"\n{3,}")

ModelT = TypeVar("ModelT", bound=BaseModel)

GMAIL_CACHE_POLICY_TEXT = (
    "Purpose: detect only monitored assignment-like or assessment-like course events. "
    "Assignment-like means homework, programming assignment, project, paper, report, worksheet, problem set, lab report, "
    "reflection, reading quiz, deliverable, submission, or other required course work with a due expectation. "
    "Assessment-like means quiz, exam, midterm, final exam, final, test, practical, oral exam, checkpoint, or similar graded assessment. "
    "Unknown means newsletters, digests, campus admin messages, generic discussion threads, office hour chatter, grade-release notices, "
    "regrade chatter, solution postings, recruiting notices, competitions, logistics that do not change a monitored item, and vague or ambiguous messages. "
    "Atomic means the message describes one concrete monitored item or one concrete updated monitored event, such as one project deadline, one quiz reminder, "
    "one final exam schedule, or one specific homework due update. "
    "Directive means the message gives a rule or instruction that mutates multiple existing monitored items, such as moving all homeworks to Friday or shifting all quizzes by one day. "
    "Do not treat informational exam descriptions, skipped sections, study advice, or format reminders as directives unless the message explicitly mutates existing monitored items. "
    "Course identity should be extracted only from clear evidence such as course codes, section titles, LMS context, or unmistakable course naming. "
    "Preserve exact date and time evidence when present in the source message. "
    "If uncertain between atomic and unknown, prefer unknown. "
    "If uncertain between directive and atomic, prefer atomic only when a single monitored item is clearly described; otherwise prefer unknown. "
    "Do not invent hidden context beyond the message. "
)

CALENDAR_CACHE_POLICY_TEXT = (
    "Purpose: detect only monitored assignment-like or assessment-like calendar events. "
    "Relevant means homework, project, paper, report, problem set, deliverable, quiz, exam, midterm, final exam, test, or similar monitored course event. "
    "Unknown means lecture, discussion, section, office hours, lab meeting, study session, social event, generic reminder, or any non-monitored event. "
    "Only infer course identity, raw_type, event_name, ordinal, confidence, and evidence from the event text. "
    "Do not invent dates or times beyond the deterministic source facts. "
    "If uncertain whether the event is monitored, prefer unknown. "
)


def run_semantic_parse_orchestrator(
    *,
    db: Session,
    source_material: dict | bytes,
    context: ParserContext,
) -> ParserOutput:
    provider = (context.provider or "").strip().lower()
    if provider == "gmail":
        if not isinstance(source_material, dict):
            raise LlmParseError(
                code="llm_gmail_payload_invalid",
                message="gmail source material must be an object",
                retryable=False,
                provider=context.provider,
                parser_version="mainline",
            )
        return _run_gmail_workflow(db=db, payload=source_material, context=context)
    if provider in {"ics", "calendar"}:
        if not isinstance(source_material, (bytes, bytearray)):
            raise LlmParseError(
                code="llm_calendar_payload_invalid",
                message="calendar source material must be bytes",
                retryable=False,
                provider=context.provider,
                parser_version="mainline",
            )
        return _run_calendar_workflow(db=db, content=bytes(source_material), context=context)
    raise LlmParseError(
        code="llm_parse_kind_invalid",
        message=f"unsupported parser provider: {provider or '-'}",
        retryable=False,
        provider=context.provider,
        parser_version="mainline",
    )


def _run_gmail_workflow(*, db: Session, payload: dict, context: ParserContext) -> ParserOutput:
    parser_name = "gmail_llm"
    message_context = _build_gmail_cache_prefix(payload=payload)
    mode, stage2_model, classify_response_id = _classify_gmail_mode(
        db=db,
        message_context=message_context,
        context=context,
    )

    if mode.mode == "unknown":
        return ParserOutput(
            records=[],
            parser_name=parser_name,
            parser_version="mainline",
            model_hint=stage2_model or "unknown_model",
        )

    base_message_id = _first_non_empty_text(
        payload.get("message_id"),
        f"gmail-{context.source_id}",
    ) or f"gmail-{context.source_id}"
    synthetic_segment = GmailPlannerSegment(
        segment_index=0,
        anchor=None,
        snippet=_first_non_empty_text(payload.get("snippet"), payload.get("body_text"), payload.get("subject")),
        segment_type_hint="directive" if mode.mode == "directive" else "atomic",
    )

    if mode.mode == "directive":
        directive, stage3_model, _directive_response_id = _extract_gmail_directive(
            db=db,
            previous_response_id=classify_response_id,
            context=context,
        )
        records: list[dict] = []
        if directive.outcome == "directive" and directive.selector is not None and directive.mutation is not None:
            records.append(
                build_directive_record(
                    base_message_id=base_message_id,
                    source_subject=_first_non_empty_text(payload.get("subject"), "Untitled") or "Untitled",
                    source_snippet=cast(str | None, payload.get("snippet")) if isinstance(payload.get("snippet"), str) else None,
                    source_from_header=cast(str | None, payload.get("from_header")) if isinstance(payload.get("from_header"), str) else None,
                    source_thread_id=cast(str | None, payload.get("thread_id")) if isinstance(payload.get("thread_id"), str) else None,
                    source_internal_date=cast(str | None, payload.get("internal_date")) if isinstance(payload.get("internal_date"), str) else None,
                    segment=synthetic_segment,
                    directive=directive,
                )
            )
        return ParserOutput(
            records=records,
            parser_name=parser_name,
            parser_version="mainline",
            model_hint=stage3_model or stage2_model or "unknown_model",
        )

    extraction, stage3_model, _atomic_response_id = _extract_gmail_atomic(
        db=db,
        previous_response_id=classify_response_id,
        context=context,
    )
    records = []
    if extraction.outcome == "event" and extraction.semantic_event_draft is not None and extraction.link_signals is not None:
        records.append(
            build_atomic_record(
                base_message_id=base_message_id,
                source_subject=_first_non_empty_text(payload.get("subject"), "Untitled") or "Untitled",
                source_snippet=cast(str | None, payload.get("snippet")) if isinstance(payload.get("snippet"), str) else None,
                source_from_header=cast(str | None, payload.get("from_header")) if isinstance(payload.get("from_header"), str) else None,
                source_thread_id=cast(str | None, payload.get("thread_id")) if isinstance(payload.get("thread_id"), str) else None,
                source_internal_date=cast(str | None, payload.get("internal_date")) if isinstance(payload.get("internal_date"), str) else None,
                segment=synthetic_segment,
                atomic_segment_count=1,
                extraction=extraction,
            )
        )
    return ParserOutput(
        records=records,
        parser_name=parser_name,
        parser_version="mainline",
        model_hint=stage3_model or stage2_model or "unknown_model",
    )


def _classify_gmail_mode(
    *,
    db: Session,
    message_context: dict[str, Any],
    context: ParserContext,
) -> tuple[GmailPurposeModeResponse, str | None, str | None]:
    invoke_request = LlmInvokeRequest(
        task_name="gmail_purpose_mode_classify",
        system_prompt=(
            "Classify one Gmail message for assignment/exam monitoring. "
            "Rules: "
            "1. If uncertain, return unknown. "
            "2. unknown is the default for digests, thread summaries, FAQs, discussion rollups, newsletters, and generic LMS wrappers. "
            "3. atomic means one concrete monitored item or one concrete monitored event update with clear evidence. "
            "4. directive means an explicit rule that changes multiple existing monitored items; pure information is not directive. "
            "5. exam format notes, skipped sections, study advice, grade release, and course policy notes are not directive. "
            "6. Canvas 'sent you a message' wrappers are not enough by themselves; classify from the actual message content only. "
            "7. Piazza daily digests and similar multi-topic summaries should be unknown unless they isolate exactly one clear monitored item. "
            "8. unknown output must be the shortest valid JSON only: {\"mode\":\"unknown\",\"evidence\":\"\"}. "
            "Do not extract semantic fields yet. Do not output any explanation outside JSON."
        ),
        user_payload={"purpose": "assignment_or_exam_monitoring"},
        cache_prefix_payload=message_context,
        output_schema_name="GmailPurposeModeResponse",
        output_schema_json=GmailPurposeModeResponse.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
        api_mode_override="responses",
        session_cache_mode="enable",
    )
    return _invoke_schema_validated(
        db=db,
        context=context,
        invoke_request=invoke_request,
        response_model=GmailPurposeModeResponse,
        stage_label="gmail_purpose_mode_classify",
        schema_invalid_code=GMAIL_SCHEMA_INVALID_CODE,
        upstream_error_code=GMAIL_UPSTREAM_ERROR_CODE,
    )


def _extract_gmail_atomic(
    *,
    db: Session,
    previous_response_id: str | None,
    context: ParserContext,
) -> tuple[GmailAtomicSegmentExtractionResponse, str | None, str | None]:
    invoke_request = LlmInvokeRequest(
        task_name="gmail_atomic_semantic_extract",
        system_prompt=(
            "Extract semantic info for one atomic course-work or assessment update from the Gmail message. "
            "Rules: "
            "1. If there is not exactly one clear monitored item, return unknown. "
            "2. Digest summaries, FAQ summaries, discussion rollups, and mixed-topic messages should be unknown unless one item is isolated with direct evidence. "
            "3. Do not convert general exam information, study advice, skipped sections, or grading chatter into a monitored item unless a specific monitored event is clearly stated. "
            "4. Only use due date and time when directly supported by the message content. "
            "5. If the course identity is weak or ambiguous, prefer unknown. "
            "6. unknown output must be exactly {\"outcome\":\"unknown\"}. "
            "7. Do not output any explanation outside JSON. "
            'Return JSON: {"outcome":"event"|"unknown",'
            '"semantic_event_draft":{"course_dept":string|null,"course_number":number|null,'
            '"course_suffix":string|null,"course_quarter":"WI"|"SP"|"SU"|"FA"|null,"course_year2":number|null,'
            '"raw_type":string|null,"event_name":string|null,"ordinal":number|null,'
            '"due_date":string|null,"due_time":string|null,"time_precision":"date_only"|"datetime"|null,'
            '"confidence":number,"evidence":string},'
            '"link_signals":{"keywords":["exam"|"midterm"|"final"],"exam_sequence":number|null,'
            '"location_text":string|null,"instructor_hint":string|null}}.'
        ),
        user_payload={"mode": "atomic", "purpose": "assignment_or_exam_monitoring"},
        previous_response_id=previous_response_id,
        output_schema_name="GmailAtomicSegmentExtractionResponse",
        output_schema_json=GmailAtomicSegmentExtractionResponse.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
        api_mode_override="responses",
        session_cache_mode="enable",
    )
    return _invoke_schema_validated(
        db=db,
        context=context,
        invoke_request=invoke_request,
        response_model=GmailAtomicSegmentExtractionResponse,
        stage_label="gmail_atomic_semantic_extract",
        schema_invalid_code=GMAIL_SCHEMA_INVALID_CODE,
        upstream_error_code=GMAIL_UPSTREAM_ERROR_CODE,
    )


def _extract_gmail_directive(
    *,
    db: Session,
    previous_response_id: str | None,
    context: ParserContext,
) -> tuple[GmailDirectiveExtractionResponse, str | None, str | None]:
    invoke_request = LlmInvokeRequest(
        task_name="gmail_directive_semantic_extract",
        system_prompt=(
            "Extract directive semantics from the Gmail message. "
            "Rules: "
            "1. Use directive only when the message explicitly changes multiple existing monitored items. "
            "2. Pure information, schedule description, exam instructions, skipped sections, grading updates, and policy notes are not directive. "
            "3. A single event change is not directive. "
            "4. If selector or mutation is incomplete, return unknown. "
            "5. If the message only describes one exam, one project, or one homework, return unknown here. "
            "6. unknown output must be exactly {\"outcome\":\"unknown\"}. "
            "7. Do not output any explanation outside JSON. "
            'Return JSON with schema: {"outcome":"directive"|"unknown",'
            '"selector":{"course_dept":string|null,"course_number":number|null,'
            '"course_suffix":string|null,"course_quarter":"WI"|"SP"|"SU"|"FA"|null,"course_year2":number|null,'
            '"family_hint":string|null,"raw_type_hint":string|null,'
            '"scope_mode":"all_matching"|"ordinal_list"|"ordinal_range","ordinal_list":[number],'
            '"ordinal_range_start":number|null,"ordinal_range_end":number|null,'
            '"current_due_weekday":"monday"|"tuesday"|"wednesday"|"thursday"|"friday"|"saturday"|"sunday"|null,'
            '"applies_to_future_only":boolean},'
            '"mutation":{"move_weekday":"monday"|"tuesday"|"wednesday"|"thursday"|"friday"|"saturday"|"sunday"|null,'
            '"set_due_date":string|null},'
            '"confidence":number,"evidence":string}.'
        ),
        user_payload={"mode": "directive", "purpose": "assignment_or_exam_monitoring"},
        previous_response_id=previous_response_id,
        output_schema_name="GmailDirectiveExtractionResponse",
        output_schema_json=GmailDirectiveExtractionResponse.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
        api_mode_override="responses",
        session_cache_mode="enable",
    )
    return _invoke_schema_validated(
        db=db,
        context=context,
        invoke_request=invoke_request,
        response_model=GmailDirectiveExtractionResponse,
        stage_label="gmail_directive_semantic_extract",
        schema_invalid_code=GMAIL_SCHEMA_INVALID_CODE,
        upstream_error_code=GMAIL_UPSTREAM_ERROR_CODE,
    )


def _run_calendar_workflow(*, db: Session, content: bytes, context: ParserContext) -> ParserOutput:
    parser_name = "calendar_deterministic"
    if not content:
        raise LlmParseError(
            code="parse_llm_empty_output",
            message="calendar source content is empty",
            retryable=False,
            provider=context.provider,
            parser_version="mainline",
        )

    try:
        calendar = Calendar.from_ical(content)
    except Exception as exc:
        raise LlmParseError(
            code="llm_calendar_payload_invalid",
            message=f"calendar parse failed: {exc}",
            retryable=False,
            provider=context.provider,
            parser_version="mainline",
        ) from exc

    records: list[dict] = []
    model_hint = "deterministic"
    for index, component in enumerate(calendar.walk()):
        if getattr(component, "name", "") != "VEVENT":
            continue
        source_facts = _extract_calendar_source_facts(component=component, source_id=context.source_id, index=index)
        relevance, stage1_model, relevance_response_id = _classify_calendar_relevance(
            db=db,
            source_facts=source_facts,
            context=context,
        )
        current_hint = stage1_model
        if relevance.outcome == "unknown":
            if current_hint:
                model_hint = current_hint
            continue
        classification, stage2_model, _semantic_response_id = _extract_calendar_semantic(
            db=db,
            previous_response_id=relevance_response_id,
            context=context,
        )
        semantic_event_draft = _build_calendar_semantic_draft(
            classification=classification.model_dump(mode="json"),
            source_facts=source_facts,
        )
        records.append(
            {
                "record_type": "calendar.event.extracted",
                "payload": {
                    "source_facts": source_facts,
                    "semantic_event_draft": semantic_event_draft,
                    "link_signals": {},
                },
            }
        )
        model_hint = stage2_model or current_hint or model_hint

    return ParserOutput(
        records=records,
        parser_name=parser_name,
        parser_version="mainline",
        model_hint=model_hint,
    )


def _classify_calendar_relevance(
    *,
    db: Session,
    source_facts: dict[str, Any],
    context: ParserContext,
) -> tuple[CalendarRelevanceResponse, str | None, str | None]:
    invoke_request = LlmInvokeRequest(
        task_name="calendar_purpose_relevance",
        system_prompt=(
            "Decide whether this calendar event is relevant to assignment/exam monitoring. "
            "Relevant means homework-like deliverables or test-like assessments. "
            "Use unknown for lectures, discussions, sections, labs, office hours, and other non-monitored items."
        ),
        user_payload={"purpose": "assignment_or_exam_monitoring"},
        cache_prefix_payload=_build_calendar_cache_prefix(source_facts=source_facts),
        output_schema_name="CalendarRelevanceResponse",
        output_schema_json=CalendarRelevanceResponse.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
        api_mode_override="responses",
        session_cache_mode="enable",
    )
    return _invoke_schema_validated(
        db=db,
        context=context,
        invoke_request=invoke_request,
        response_model=CalendarRelevanceResponse,
        stage_label="calendar_purpose_relevance",
        schema_invalid_code=CALENDAR_SCHEMA_INVALID_CODE,
        upstream_error_code=CALENDAR_UPSTREAM_ERROR_CODE,
    )


def _extract_calendar_semantic(
    *,
    db: Session,
    previous_response_id: str | None,
    context: ParserContext,
) -> tuple[CalendarSemanticEventClassification, str | None, str | None]:
    invoke_request = LlmInvokeRequest(
        task_name="calendar_semantic_extract",
        system_prompt=(
            "Extract the minimal semantic classification for one relevant assignment/test calendar event. "
            "Only infer course identity, raw_type, event_name, ordinal, confidence, and evidence. "
            "Do not infer due date/time or link metadata."
        ),
        user_payload={"purpose": "assignment_or_exam_monitoring"},
        previous_response_id=previous_response_id,
        output_schema_name="CalendarSemanticEventClassification",
        output_schema_json=CalendarSemanticEventClassification.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
        api_mode_override="responses",
        session_cache_mode="enable",
    )
    return _invoke_schema_validated(
        db=db,
        context=context,
        invoke_request=invoke_request,
        response_model=CalendarSemanticEventClassification,
        stage_label="calendar_semantic_extract",
        schema_invalid_code=CALENDAR_SCHEMA_INVALID_CODE,
        upstream_error_code=CALENDAR_UPSTREAM_ERROR_CODE,
    )


def _invoke_schema_validated(
    *,
    db: Session,
    context: ParserContext,
    invoke_request: LlmInvokeRequest,
    response_model: type[ModelT],
    stage_label: str,
    schema_invalid_code: str,
    upstream_error_code: str,
) -> tuple[ModelT, str | None, str | None]:
    parsed: ModelT | None = None
    invoke_result: LlmInvokeResult | None = None
    for attempt in range(1, LLM_FORMAT_MAX_ATTEMPTS + 1):
        try:
            invoke_result = invoke_llm_json(db, invoke_request=invoke_request)
        except LlmGatewayError as exc:
            raise _map_llm_error(
                exc=exc,
                provider=context.provider,
                schema_invalid_code=schema_invalid_code,
                upstream_error_code=upstream_error_code,
            ) from exc

        try:
            parsed = response_model.model_validate(invoke_result.json_object)
            break
        except ValidationError as exc:
            if attempt < LLM_FORMAT_MAX_ATTEMPTS:
                logger.warning(
                    "semantic_orchestrator.format_retry request_id=%s source_id=%s task_name=%s error_code=%s attempt=%s/%s",
                    context.request_id or "-",
                    context.source_id,
                    stage_label,
                    schema_invalid_code,
                    attempt,
                    LLM_FORMAT_MAX_ATTEMPTS,
                )
                continue
            logger.warning(
                "semantic_orchestrator.format_retry_exhausted request_id=%s source_id=%s task_name=%s error_code=%s attempt=%s/%s",
                context.request_id or "-",
                context.source_id,
                stage_label,
                schema_invalid_code,
                attempt,
                LLM_FORMAT_MAX_ATTEMPTS,
            )
            raise LlmParseError(
                code=schema_invalid_code,
                message=f"llm schema invalid ({stage_label}): {exc.errors()}",
                retryable=False,
                provider=context.provider,
                parser_version="mainline",
            ) from exc

    if parsed is None or invoke_result is None:
        raise LlmParseError(
            code=schema_invalid_code,
            message=f"llm returned no valid payload after retries ({stage_label})",
            retryable=False,
            provider=context.provider,
            parser_version="mainline",
        )

    model_hint = invoke_result.model if isinstance(invoke_result.model, str) and invoke_result.model.strip() else None
    return parsed, model_hint, invoke_result.response_id


def _map_llm_error(
    *,
    exc: LlmGatewayError,
    provider: str,
    schema_invalid_code: str,
    upstream_error_code: str,
) -> LlmParseError:
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
            code=schema_invalid_code,
            message=str(exc),
            retryable=False,
            provider=provider,
            parser_version="mainline",
        )
    if exc.code == "parse_llm_upstream_error":
        return LlmParseError(
            code=upstream_error_code,
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


def _extract_calendar_source_facts(*, component: Any, source_id: int, index: int) -> dict:
    summary = _sanitize_calendar_text(_coerce_component_text(component.get("summary"))) or "Untitled"
    description = _extract_component_description(component)
    status = _coerce_component_text(component.get("status"))
    location = _coerce_component_text(component.get("location"))
    organizer = _coerce_component_text(component.get("organizer"))
    uid_value = _coerce_component_text(component.get("uid")) or f"component-{source_id}-{index}"
    recurrence_id = _coerce_component_text(component.get("recurrence-id"))
    dtstart_value = _component_datetime(component.get("dtstart"))
    dtend_value = _component_datetime(component.get("dtend")) or dtstart_value
    if dtstart_value is None or dtend_value is None:
        raise LlmParseError(
            code="llm_calendar_payload_invalid",
            message="calendar event missing dtstart/dtend",
            retryable=False,
            provider="ics",
            parser_version="mainline",
        )
    external_event_id = build_external_event_id(uid=uid_value, recurrence_id=recurrence_id)
    return SourceFacts.model_validate(
        {
            "external_event_id": external_event_id,
            "component_key": build_component_key(uid=uid_value, recurrence_id=recurrence_id),
            "source_title": summary[:512],
            "source_summary": description[:1024] if description else None,
            "source_dtstart_utc": dtstart_value.isoformat(),
            "source_dtend_utc": dtend_value.isoformat(),
            "status": status,
            "location": location,
            "organizer": organizer,
        }
    ).model_dump(mode="json")


def _build_gmail_cache_prefix(*, payload: dict) -> dict[str, Any]:
    return {
        "policy_version": "gmail-cache-v1",
        "policy_text": GMAIL_CACHE_POLICY_TEXT,
        "source_message": {
            "message_id": payload.get("message_id"),
            "subject": payload.get("subject"),
            "snippet": payload.get("snippet"),
            "body_text": payload.get("body_text"),
            "from_header": payload.get("from_header"),
            "thread_id": payload.get("thread_id"),
            "internal_date": payload.get("internal_date"),
        },
    }


def _build_calendar_cache_prefix(*, source_facts: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy_version": "calendar-cache-v1",
        "policy_text": CALENDAR_CACHE_POLICY_TEXT,
        "source_event": source_facts,
    }


def _build_calendar_semantic_draft(*, classification: dict, source_facts: dict) -> dict:
    dtstart = _parse_optional_datetime(source_facts.get("source_dtstart_utc"))
    source_precision = source_facts.get("source_time_precision")
    due_date_value, due_time_value, time_precision = split_due_parts(
        due_at=dtstart,
        time_precision=str(source_precision or "datetime"),
    )
    return normalize_semantic_event(
        {
            **classification,
            "due_date": due_date_value.isoformat() if due_date_value is not None else None,
            "due_time": due_time_value.isoformat() if due_time_value is not None else None,
            "time_precision": time_precision,
        },
        fallback_due_raw=source_facts.get("source_dtstart_utc"),
    )


def _coerce_component_text(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "to_ical"):
        try:
            rendered = value.to_ical().decode("utf-8")
        except Exception:
            rendered = str(value)
    else:
        rendered = str(value)
    cleaned = rendered.strip()
    return cleaned or None


def _extract_component_description(component: Any) -> str | None:
    description = _sanitize_calendar_text(_coerce_component_text(component.get("description")))
    if description:
        return description[:1024]
    alt_desc = _sanitize_calendar_text(
        _coerce_component_text(component.get("X-ALT-DESC"))
        or _coerce_component_text(component.get("x-alt-desc"))
    )
    if alt_desc:
        return alt_desc[:1024]
    return None


def _component_datetime(value: object):
    if value is None:
        return None
    dt = getattr(value, "dt", value)
    if hasattr(dt, "tzinfo"):
        if getattr(dt, "tzinfo", None) is None:
            return dt.replace(tzinfo=_utc()) if hasattr(dt, "replace") else None
        return dt.astimezone(_utc()) if hasattr(dt, "astimezone") else None
    if hasattr(dt, "year") and hasattr(dt, "month") and hasattr(dt, "day"):
        from datetime import datetime

        return datetime(dt.year, dt.month, dt.day, 23, 59, tzinfo=_utc())
    return None


def _sanitize_calendar_text(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    text = _HTML_SCRIPT_STYLE_RE.sub(" ", text)
    text = _HTML_BREAK_RE.sub("\n", text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE_RE.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = _BLANK_LINE_RE.sub("\n\n", text)
    cleaned = text.strip()
    return cleaned or None


def _parse_optional_datetime(value: object):
    if not isinstance(value, str) or not value.strip():
        return None
    from datetime import datetime, timezone

    raw = value.strip()
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _first_non_empty_text(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
    return None


def _utc():
    from datetime import timezone

    return timezone.utc


__all__ = [
    "run_semantic_parse_orchestrator",
]
