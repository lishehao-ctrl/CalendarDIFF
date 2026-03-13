from __future__ import annotations

from datetime import date, datetime, timezone
import logging

from icalendar import Calendar
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.modules.common.payload_schemas import SourceFacts
from app.modules.core_ingest.semantic_event_service import normalize_semantic_event
from app.modules.ingestion.ics_delta.fingerprint import build_component_key, build_external_event_id
from app.modules.ingestion.llm_parsers.contracts import LlmParseError, ParserContext, ParserOutput
from app.modules.ingestion.llm_parsers.schemas import SemanticEventDraftResponse
from app.modules.llm_gateway import (
    LLM_FORMAT_MAX_ATTEMPTS,
    LlmGatewayError,
    LlmInvokeRequest,
    invoke_llm_json,
)

CALENDAR_SCHEMA_INVALID_CODE = "parse_llm_calendar_schema_invalid"
CALENDAR_UPSTREAM_ERROR_CODE = "parse_llm_calendar_upstream_error"
logger = logging.getLogger(__name__)


def parse_calendar_content(*, db: Session, content: bytes, context: ParserContext) -> ParserOutput:
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

        source_facts = _extract_source_facts(component=component, source_id=context.source_id, index=index)
        semantic_extract, parse_model_hint = parse_semantic_event_draft_text(
            db=db,
            source_facts=source_facts,
            context=context,
            task_name="calendar_event_semantic_extract",
        )
        if parse_model_hint:
            model_hint = parse_model_hint

        payload = {
            "source_facts": source_facts,
            "semantic_event_draft": semantic_extract["semantic_event_draft"],
            "link_signals": semantic_extract["link_signals"],
        }
        records.append({"record_type": "calendar.event.extracted", "payload": payload})

    return ParserOutput(
        records=records,
        parser_name=parser_name,
        parser_version="mainline",
        model_hint=model_hint,
    )


def parse_semantic_event_draft_text(
    *,
    db: Session,
    source_facts: dict,
    context: ParserContext,
    task_name: str,
) -> tuple[dict, str | None]:
    source_title = str(source_facts.get("source_title") or "").strip()
    source_summary = str(source_facts.get("source_summary") or "").strip()
    source_location = str(source_facts.get("location") or "").strip()
    source_organizer = str(source_facts.get("organizer") or "").strip()
    if not source_title and not source_summary:
        raise LlmParseError(
            code="llm_calendar_payload_invalid",
            message="calendar event source text is empty for semantic parse",
            retryable=False,
            provider=context.provider,
            parser_version="mainline",
        )

    invoke_request = LlmInvokeRequest(
        task_name=task_name,
        system_prompt=(
            "Extract semantic academic event data from calendar text. "
            "Return JSON with schema: "
            '{"semantic_event_draft":{"course_dept":string|null,"course_number":number|null,"course_suffix":string|null,'
            '"course_quarter":"WI"|"SP"|"SU"|"FA"|null,"course_year2":number|null,'
            '"raw_type":string|null,"event_name":string|null,"ordinal":number|null,'
            '"due_date":string|null,"due_time":string|null,"time_precision":"date_only"|"datetime"|null,'
            '"confidence":number,"evidence":string},'
            '"link_signals":{"keywords":["exam"|"midterm"|"final"],"exam_sequence":number|null,'
            '"location_text":string|null,"instructor_hint":string|null}}. '
            "Use semantic_event_draft as the only event schema. "
            "Use ISO-8601 for due_date (YYYY-MM-DD) and due_time (HH:MM[:SS]) when present. "
            "Use null when uncertain and copy evidence from the input text."
        ),
        user_payload={
            "source_id": context.source_id,
            "provider": context.provider,
            "source_kind": context.source_kind,
            "source_facts": {
                "source_title": source_title,
                "source_summary": source_summary,
                "location": source_location or None,
                "organizer": source_organizer or None,
                "source_dtstart_utc": source_facts.get("source_dtstart_utc"),
                "source_dtend_utc": source_facts.get("source_dtend_utc"),
            },
        },
        output_schema_name="SemanticEventDraftResponse",
        output_schema_json=SemanticEventDraftResponse.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
    )

    for attempt in range(1, LLM_FORMAT_MAX_ATTEMPTS + 1):
        try:
            invoke_result = invoke_llm_json(db, invoke_request=invoke_request)
        except LlmGatewayError as exc:
            raise _map_llm_error(exc, provider=context.provider) from exc

        try:
            parsed = SemanticEventDraftResponse.model_validate(invoke_result.json_object)
            return {
                "semantic_event_draft": normalize_semantic_event(
                    parsed.semantic_event_draft.model_dump(mode="json"),
                    fallback_due_raw=source_facts.get("source_dtstart_utc"),
                ),
                "link_signals": parsed.link_signals.model_dump(),
            }, invoke_result.model
        except ValidationError as exc:
            if attempt < LLM_FORMAT_MAX_ATTEMPTS:
                logger.warning(
                    "calendar_parser.format_retry request_id=%s source_id=%s task_name=%s error_code=%s attempt=%s/%s",
                    context.request_id or "-",
                    context.source_id,
                    task_name,
                    CALENDAR_SCHEMA_INVALID_CODE,
                    attempt,
                    LLM_FORMAT_MAX_ATTEMPTS,
                )
                continue
            logger.warning(
                "calendar_parser.format_retry_exhausted request_id=%s source_id=%s task_name=%s error_code=%s attempt=%s/%s",
                context.request_id or "-",
                context.source_id,
                task_name,
                CALENDAR_SCHEMA_INVALID_CODE,
                attempt,
                LLM_FORMAT_MAX_ATTEMPTS,
            )
            raise LlmParseError(
                code=CALENDAR_SCHEMA_INVALID_CODE,
                message=f"calendar llm schema invalid: {exc.errors()}",
                retryable=False,
                provider=context.provider,
                parser_version="mainline",
            ) from exc

    raise LlmParseError(
        code=CALENDAR_SCHEMA_INVALID_CODE,
        message="calendar llm parser returned no valid payload after retries",
        retryable=False,
        provider=context.provider,
        parser_version="mainline",
    )


def _extract_source_facts(*, component, source_id: int, index: int) -> dict:
    summary = _coerce_component_text(component.get("summary")) or "Untitled"
    description = _coerce_component_text(component.get("description"))
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


def _coerce_component_text(value) -> str | None:
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


def _component_datetime(value) -> datetime | None:
    if value is None:
        return None
    decoded = getattr(value, "dt", value)
    if isinstance(decoded, datetime):
        if decoded.tzinfo is None:
            return decoded.replace(tzinfo=timezone.utc)
        return decoded.astimezone(timezone.utc)
    if isinstance(decoded, date):
        return datetime(decoded.year, decoded.month, decoded.day, 23, 59, tzinfo=timezone.utc)
    return None


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
            code=CALENDAR_SCHEMA_INVALID_CODE,
            message=str(exc),
            retryable=False,
            provider=provider,
            parser_version="mainline",
        )
    if exc.code == "parse_llm_upstream_error":
        return LlmParseError(
            code=CALENDAR_UPSTREAM_ERROR_CODE,
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
