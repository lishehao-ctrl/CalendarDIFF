from __future__ import annotations

import logging
import re
from typing import Any, TypeVar, cast

from icalendar import Calendar
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.modules.common.payload_schemas import SourceFacts
from app.modules.common.text_sanitize import sanitize_markup_text
from app.modules.core_ingest.semantic_event_service import normalize_semantic_event, split_due_parts
from app.modules.ingestion.ics_delta.fingerprint import build_component_key, build_external_event_id
from app.modules.ingestion.llm_parsers.contracts import LlmParseError, ParserContext, ParserOutput
from app.modules.ingestion.llm_parsers.gmail_parser_records import build_atomic_record, build_directive_record
from app.modules.ingestion.llm_parsers.schemas import (
    CalendarRelevanceResponse,
    CalendarSemanticEventClassification,
    GmailAtomicIdentityExtractionResponse,
    GmailAtomicSegmentExtractionResponse,
    GmailAtomicTimeResolutionResponse,
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

GMAIL_BROAD_AUDIENCE_RULE_TEXT = (
    "A message about one concrete monitored item stays atomic even if it applies to all sections, all students, "
    "or the whole class. Broad audience alone is not directive evidence. "
)

GMAIL_DIRECTIVE_STRUCTURE_RULE_TEXT = (
    "Directive requires a rule over multiple existing monitored items, such as all future matching items, an ordinal list, "
    "an ordinal range, or another recurring future rule. "
)

GMAIL_MODE_FEWSHOT_TEXT = (
    'Examples: "Project 2 extended for all sections" => atomic. '
    '"Homework 3 now due Friday for all students" => atomic. '
    '"All future quizzes that were due Friday now move to Monday" => directive. '
    '"Homework 2 through Homework 4 now due 2026-04-10" => directive. '
)

GMAIL_ATOMIC_IDENTITY_RULE_TEXT = (
    "For atomic extraction, keep raw_type and event_name close to the source alias used in the authoritative graded-item phrase. "
    "Do not over-canonicalize aliases across families because alias merging happens later in the family layer. "
    "If the message says HW 27, prefer raw_type=HW and event_name=HW 27. "
    "If the message says Write-up 2, prefer raw_type=Write-up and event_name=Write-up 2. "
    "If the message says Take-home Final, prefer raw_type=Take-home Final and event_name=Take-home Final. "
    "Normalize case and spacing lightly so parsing is stable, but preserve the alias family from the source phrase. "
    "If subject and body use different aliases, prefer the alias from the main authoritative timing sentence in the body over the subject wrapper wording. "
    "If the body explicitly says that multiple aliases refer to the same graded item, choose exactly one final alias instead of explaining the alias relationship. "
    "Prefer the most specific graded-item alias, not the shortest shorthand, when an equivalence sentence lists several aliases for the same item. "
    "Do not use generic raw_type labels such as assignment, coursework, extension, update, reminder, due date change, or assignment_extension. "
    "Evidence must be a short supporting phrase only and must not explain alternate aliases or reasoning. "
    "event_name must stay focused on the monitored item identity only; do not include change words like extended, extension, updated, moved, rescheduled, timing confirmed, or deadline change in event_name. "
)

GMAIL_ATOMIC_IDENTITY_FEWSHOT_TEXT = (
    'Identity examples: "Project 2 deadline extension" => raw_type="Project", event_name="Project 2". '
    '"Project Milestone 11 due date updated" => raw_type="Project Milestone", event_name="Project Milestone 11". '
    '"HW 27 is posted" => raw_type="HW", event_name="HW 27". '
    '"Write-up 2 now lands at ..." => raw_type="Write-up", event_name="Write-up 2". '
    '"Take-home final due time revised" => raw_type="Take-home Final", event_name="Take-home Final". '
    '"Problem Set 4 deadline moved earlier" => raw_type="Problem Set", event_name="Problem Set 4". '
    'If the subject says "HW 26 posted" but the authoritative timing sentence says "Problem Set 26 is posted", prefer raw_type="Problem Set" and event_name="Problem Set 26". '
    'If the body says "Deliverable 3, Project Milestone 3, and Milestone 3 all refer to the same deliverable", choose raw_type="Project Milestone" and event_name="Project Milestone 3". '
)

GMAIL_DIRECTIVE_FEWSHOT_TEXT = (
    'Directive examples: "All future quizzes that were due Friday now move to Monday" => directive with all_matching. '
    '"Homework 2 through Homework 4 now due 2026-04-10" => directive with ordinal_range. '
    '"Checkpoint 2 and 4 now due 2026-04-10" => directive with ordinal_list. '
    'Negative example: "Project 2 extended for all sections" => unknown here because atomic lane should handle one item. '
)

GMAIL_TIME_RESOLUTION_RULE_TEXT = (
    "For time resolution, use source_message.internal_date as the anchor for relative dates and for month/day phrases without an explicit year. "
    "If a due phrase gives month and day but no year, infer the year from internal_date unless the message explicitly says a different year. "
    "For new or updated graded items, choose the current authoritative due date/time, not the previous posted time or historical comparison timestamp. "
    "When multiple dates appear, prefer the one tied to phrases like now due, is due, deadline is, lands at, closes at, or submission deadline. "
    "resolved_due_time must keep the wall-clock time stated in the message and must not be converted to UTC. "
)

GMAIL_TIME_RESOLUTION_FEWSHOT_TEXT = (
    'Time examples: with internal_date in December 2026, "Friday, December 25 at 11:00 PM UTC" => 2026-12-25 and 23:00:00. '
    'With internal_date 2026-07-19, "Sunday, July 19 at 11:59 PM PT" => 2026-07-19 and 23:59:00. '
    'With internal_date 2026-12-01, "this Monday at 11:59 PM" => the next upcoming Monday at 23:59:00. '
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
    mode, stage2_model, _classify_response_id = _classify_gmail_mode(
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
        snippet=_first_non_empty_text(_sanitize_gmail_text(payload.get("snippet")), _sanitize_gmail_text(payload.get("body_text")), _sanitize_gmail_text(payload.get("subject"))),
        segment_type_hint="directive" if mode.mode == "directive" else "atomic",
    )

    if mode.mode == "directive":
        directive: GmailDirectiveExtractionResponse | None = None
        directive_model_hint: str | None = None
        directive_fallback_reason: str | None = None
        try:
            directive, directive_model_hint, _directive_response_id = _extract_gmail_directive(
                db=db,
                message_context=message_context,
                context=context,
            )
        except LlmParseError as exc:
            if exc.code != GMAIL_SCHEMA_INVALID_CODE:
                raise
            directive_fallback_reason = "directive_schema_invalid"
            logger.info(
                "semantic_orchestrator.directive_atomic_fallback request_id=%s source_id=%s reason=%s",
                context.request_id or "-",
                context.source_id,
                directive_fallback_reason,
            )

        if directive is not None and directive.outcome == "directive" and directive.selector is not None and directive.mutation is not None:
            records: list[dict] = [
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
            ]
            return ParserOutput(
                records=records,
                parser_name=parser_name,
                parser_version="mainline",
                model_hint=directive_model_hint or stage2_model or "unknown_model",
            )

        if directive_fallback_reason is None:
            directive_fallback_reason = "directive_unknown"
            logger.info(
                "semantic_orchestrator.directive_atomic_fallback request_id=%s source_id=%s reason=%s",
                context.request_id or "-",
                context.source_id,
                directive_fallback_reason,
            )

        extraction, fallback_model_hint, _atomic_response_id = _extract_gmail_atomic(
            db=db,
            payload=payload,
            message_context=message_context,
            context=context,
        )
        records = _build_gmail_atomic_records(
            payload=payload,
            base_message_id=base_message_id,
            segment=synthetic_segment,
            extraction=extraction,
        )
        return ParserOutput(
            records=records,
            parser_name=parser_name,
            parser_version="mainline",
            model_hint=fallback_model_hint or directive_model_hint or stage2_model or "unknown_model",
        )

    extraction, stage3_model, _atomic_response_id = _extract_gmail_atomic(
        db=db,
        payload=payload,
        message_context=message_context,
        context=context,
    )
    records = _build_gmail_atomic_records(
        payload=payload,
        base_message_id=base_message_id,
        segment=synthetic_segment,
        extraction=extraction,
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
            f"9. {GMAIL_BROAD_AUDIENCE_RULE_TEXT}"
            f"10. {GMAIL_DIRECTIVE_STRUCTURE_RULE_TEXT}"
            f"11. {GMAIL_MODE_FEWSHOT_TEXT}"
            "Do not extract semantic fields yet. Do not output any explanation outside JSON."
        ),
        user_payload={
            "purpose": "assignment_or_exam_monitoring",
            "message_context": message_context,
        },
        cache_prefix_payload={"cache_scope": "gmail_purpose_mode_classify:v2"},
        cache_task_prompt=True,
        output_schema_name="GmailPurposeModeResponse",
        output_schema_json=GmailPurposeModeResponse.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
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
    payload: dict[str, Any],
    message_context: dict[str, Any],
    context: ParserContext,
) -> tuple[GmailAtomicSegmentExtractionResponse, str | None, str | None]:
    identity, stage3_model, _identity_response_id = _extract_gmail_atomic_identity(
        db=db,
        message_context=message_context,
        context=context,
    )
    if identity.outcome != "event" or identity.semantic_identity_draft is None or identity.link_signals is None:
        return (
            GmailAtomicSegmentExtractionResponse(
                outcome="unknown",
                semantic_event_draft=None,
                link_signals=None,
            ),
            stage3_model,
            None,
        )

    time_resolution, stage4_model, time_response_id = _resolve_gmail_atomic_time(
        db=db,
        message_context=message_context,
        identity=identity,
        payload=payload,
        context=context,
    )
    if time_resolution.outcome != "resolved" or time_resolution.resolved_due_date is None or time_resolution.time_precision is None:
        return (
            GmailAtomicSegmentExtractionResponse(
                outcome="unknown",
                semantic_event_draft=None,
                link_signals=None,
            ),
            stage4_model or stage3_model,
            time_response_id,
        )

    return (
        _build_gmail_atomic_extraction(
            identity=identity,
            time_resolution=time_resolution,
        ),
        stage4_model or stage3_model,
        time_response_id,
    )


def _extract_gmail_atomic_identity(
    *,
    db: Session,
    message_context: dict[str, Any],
    context: ParserContext,
) -> tuple[GmailAtomicIdentityExtractionResponse, str | None, str | None]:
    invoke_request = LlmInvokeRequest(
        task_name="gmail_atomic_identity_extract",
        system_prompt=(
            "Extract stable identity info for one atomic course-work or assessment update from the Gmail message. "
            "Rules: "
            "1. If there is not exactly one clear monitored item, return unknown. "
            "2. Digest summaries, FAQ summaries, discussion rollups, and mixed-topic messages should be unknown unless one item is isolated with direct evidence. "
            "3. Do not convert general exam information, study advice, skipped sections, or grading chatter into a monitored item unless a specific monitored event is clearly stated. "
            "4. This stage is for stable item identity only, not time normalization. "
            "5. If the course identity is weak or ambiguous, prefer unknown. "
            f"6. {GMAIL_BROAD_AUDIENCE_RULE_TEXT}"
            "7. If one concrete monitored item gets a new date or time, keep it atomic even when the audience is every section or the whole class. "
            '8. Example: "Project 2 extended for all sections" should still be event, not unknown. '
            f"9. {GMAIL_ATOMIC_IDENTITY_RULE_TEXT}"
            f"10. {GMAIL_ATOMIC_IDENTITY_FEWSHOT_TEXT}"
            "11. unknown output must be exactly {\"outcome\":\"unknown\"}. "
            "12. Do not output any explanation outside JSON. "
            'Return JSON: {"outcome":"event"|"unknown",'
            '"semantic_identity_draft":{"course_dept":string|null,"course_number":number|null,'
            '"course_suffix":string|null,"course_quarter":"WI"|"SP"|"SU"|"FA"|null,"course_year2":number|null,'
            '"raw_type":string|null,"event_name":string|null,"ordinal":number|null,"confidence":number,"evidence":string},'
            '"link_signals":{"keywords":["exam"|"midterm"|"final"],"exam_sequence":number|null,'
            '"location_text":string|null,"instructor_hint":string|null}}.'
        ),
        user_payload={"mode": "atomic", "purpose": "assignment_or_exam_monitoring"},
        cache_prefix_payload=message_context,
        output_schema_name="GmailAtomicIdentityExtractionResponse",
        output_schema_json=GmailAtomicIdentityExtractionResponse.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
        session_cache_mode="enable",
    )
    return _invoke_schema_validated(
        db=db,
        context=context,
        invoke_request=invoke_request,
        response_model=GmailAtomicIdentityExtractionResponse,
        stage_label="gmail_atomic_identity_extract",
        schema_invalid_code=GMAIL_SCHEMA_INVALID_CODE,
        upstream_error_code=GMAIL_UPSTREAM_ERROR_CODE,
    )


def _resolve_gmail_atomic_time(
    *,
    db: Session,
    payload: dict[str, Any],
    message_context: dict[str, Any],
    identity: GmailAtomicIdentityExtractionResponse,
    context: ParserContext,
) -> tuple[GmailAtomicTimeResolutionResponse, str | None, str | None]:
    identity_payload = identity.semantic_identity_draft.model_dump(mode="json") if identity.semantic_identity_draft is not None else {}
    invoke_request = LlmInvokeRequest(
        task_name="gmail_atomic_time_resolve",
        system_prompt=(
            "Resolve the due date and time for one already-identified atomic monitored item from the Gmail message. "
            "Rules: "
            "1. Use only the current authoritative due phrase for the monitored item, not historical comparison dates unless they are explicitly the new due date. "
            "2. This stage resolves time only; the item identity is already provided in task_input.identity_draft. "
            f"3. {GMAIL_TIME_RESOLUTION_RULE_TEXT}"
            f"4. {GMAIL_TIME_RESOLUTION_FEWSHOT_TEXT}"
            "5. resolution_basis should be a short label, not a long sentence. "
            '6. unknown output must be exactly {"outcome":"unknown"}. '
            "7. Do not output any explanation outside JSON. "
            'Return JSON: {"outcome":"resolved"|"unknown",'
            '"source_time_phrase":string|null,'
            '"resolved_due_date":string|null,'
            '"resolved_due_time":string|null,'
            '"time_precision":"date_only"|"datetime"|null,'
            '"resolution_basis":string|null,'
            '"confidence":number,'
            '"evidence":string}.'
        ),
        user_payload={
            "mode": "atomic_time_resolve",
            "purpose": "assignment_or_exam_monitoring",
            "identity_draft": identity_payload,
            "source_internal_date": payload.get("internal_date"),
        },
        cache_prefix_payload=message_context,
        output_schema_name="GmailAtomicTimeResolutionResponse",
        output_schema_json=GmailAtomicTimeResolutionResponse.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
        session_cache_mode="enable",
    )
    return _invoke_schema_validated(
        db=db,
        context=context,
        invoke_request=invoke_request,
        response_model=GmailAtomicTimeResolutionResponse,
        stage_label="gmail_atomic_time_resolve",
        schema_invalid_code=GMAIL_SCHEMA_INVALID_CODE,
        upstream_error_code=GMAIL_UPSTREAM_ERROR_CODE,
    )


def _extract_gmail_directive(
    *,
    db: Session,
    message_context: dict[str, Any],
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
            f"6. {GMAIL_BROAD_AUDIENCE_RULE_TEXT}"
            f"7. {GMAIL_DIRECTIVE_STRUCTURE_RULE_TEXT}"
            "8. all sections, all students, or whole class alone are never enough for directive. "
            "9. set_due_date must be YYYY-MM-DD only; do not include time in set_due_date. "
            f"10. {GMAIL_DIRECTIVE_FEWSHOT_TEXT}"
            "11. unknown output must be exactly {\"outcome\":\"unknown\"}. Return only that object when not directive. "
            "12. Do not output any explanation outside JSON. "
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
        cache_prefix_payload=message_context,
        output_schema_name="GmailDirectiveExtractionResponse",
        output_schema_json=GmailDirectiveExtractionResponse.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
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
        relevance, stage1_model, _relevance_response_id = _classify_calendar_relevance(
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
            source_facts=source_facts,
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
    source_facts: dict[str, Any],
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
        cache_prefix_payload=_build_calendar_cache_prefix(source_facts=source_facts),
        output_schema_name="CalendarSemanticEventClassification",
        output_schema_json=CalendarSemanticEventClassification.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
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
            "subject": _sanitize_gmail_text(payload.get("subject")),
            "snippet": _sanitize_gmail_text(payload.get("snippet")),
            "body_text": _sanitize_gmail_text(payload.get("body_text"), max_length=12000),
            "from_header": _sanitize_gmail_text(payload.get("from_header")),
            "thread_id": payload.get("thread_id"),
            "internal_date": payload.get("internal_date"),
        },
    }


def _build_gmail_atomic_records(
    *,
    payload: dict[str, Any],
    base_message_id: str,
    segment: GmailPlannerSegment,
    extraction: GmailAtomicSegmentExtractionResponse,
) -> list[dict]:
    records: list[dict] = []
    if extraction.outcome == "event" and extraction.semantic_event_draft is not None and extraction.link_signals is not None:
        records.append(
            build_atomic_record(
                base_message_id=base_message_id,
                source_subject=_first_non_empty_text(payload.get("subject"), "Untitled") or "Untitled",
                source_snippet=cast(str | None, payload.get("snippet")) if isinstance(payload.get("snippet"), str) else None,
                source_from_header=cast(str | None, payload.get("from_header")) if isinstance(payload.get("from_header"), str) else None,
                source_thread_id=cast(str | None, payload.get("thread_id")) if isinstance(payload.get("thread_id"), str) else None,
                source_internal_date=cast(str | None, payload.get("internal_date")) if isinstance(payload.get("internal_date"), str) else None,
                segment=segment,
                atomic_segment_count=1,
                extraction=extraction,
            )
        )
    return records


def _build_gmail_atomic_extraction(
    *,
    identity: GmailAtomicIdentityExtractionResponse,
    time_resolution: GmailAtomicTimeResolutionResponse,
) -> GmailAtomicSegmentExtractionResponse:
    if identity.semantic_identity_draft is None or identity.link_signals is None:
        return GmailAtomicSegmentExtractionResponse(outcome="unknown", semantic_event_draft=None, link_signals=None)
    if time_resolution.resolved_due_date is None or time_resolution.time_precision is None:
        return GmailAtomicSegmentExtractionResponse(outcome="unknown", semantic_event_draft=None, link_signals=None)

    due_time_value = (
        time_resolution.resolved_due_time.isoformat()
        if time_resolution.resolved_due_time is not None and time_resolution.time_precision == "datetime"
        else None
    )
    semantic_event_draft = normalize_semantic_event(
        {
            **identity.semantic_identity_draft.model_dump(mode="json"),
            "due_date": time_resolution.resolved_due_date.isoformat(),
            "due_time": due_time_value,
            "time_precision": time_resolution.time_precision,
            "confidence": min(
                float(identity.semantic_identity_draft.confidence or 0.0),
                float(time_resolution.confidence or 0.0),
            ),
            "evidence": time_resolution.evidence or identity.semantic_identity_draft.evidence,
        }
    )
    return GmailAtomicSegmentExtractionResponse.model_validate(
        {
            "outcome": "event",
            "semantic_event_draft": semantic_event_draft,
            "link_signals": identity.link_signals.model_dump(mode="json"),
        }
    )


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
    return sanitize_markup_text(value, max_length=1024)


def _sanitize_gmail_text(value: object, *, max_length: int | None = 2048) -> str | None:
    if not isinstance(value, str):
        return None
    return sanitize_markup_text(value, max_length=max_length)


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
