from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import logging

from icalendar import Calendar
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.modules.ingestion.ics_delta.fingerprint import build_external_event_id
from app.modules.ingestion.llm_parsers.contracts import LlmParseError, ParserContext, ParserOutput
from app.modules.ingestion.llm_parsers.schemas import EventEnrichmentResponse
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
    parser_name = "calendar_v2_deterministic"
    if not content:
        raise LlmParseError(
            code="parse_llm_empty_output",
            message="calendar source content is empty",
            retryable=False,
            provider=context.provider,
            parser_version="v2",
        )

    try:
        calendar = Calendar.from_ical(content)
    except Exception as exc:
        raise LlmParseError(
            code="llm_calendar_payload_invalid",
            message=f"calendar parse failed: {exc}",
            retryable=False,
            provider=context.provider,
            parser_version="v2",
        ) from exc

    records: list[dict] = []
    model_hint = "deterministic"
    for index, component in enumerate(calendar.walk()):
        if getattr(component, "name", "") != "VEVENT":
            continue

        canonical = _extract_source_canonical(component=component, source_id=context.source_id, index=index)
        enrichment, parse_model_hint = parse_event_enrichment_text(
            db=db,
            source_canonical=canonical,
            context=context,
            task_name="calendar_event_enrichment",
        )
        if parse_model_hint:
            model_hint = parse_model_hint

        payload = {
            "source_canonical": canonical,
            "enrichment": {
                "course_parse": enrichment["course_parse"],
                "event_parts": enrichment["event_parts"],
                "link_signals": enrichment["link_signals"],
                "payload_schema_version": "obs_v3",
            },
        }
        records.append(
            {
                "record_type": "calendar.event.extracted",
                "payload": payload,
            }
        )

    return ParserOutput(
        records=records,
        parser_name=parser_name,
        parser_version="v2",
        model_hint=model_hint,
    )


def parse_course_parse_text(
    *,
    db: Session,
    source_canonical: dict,
    context: ParserContext,
    task_name: str,
) -> tuple[dict, str | None]:
    source_title = str(source_canonical.get("source_title") or "").strip()
    source_summary = str(source_canonical.get("source_summary") or "").strip()
    source_location = str(source_canonical.get("location") or "").strip()
    source_organizer = str(source_canonical.get("organizer") or "").strip()
    if not source_title and not source_summary:
        raise LlmParseError(
            code="llm_calendar_payload_invalid",
            message="calendar event source text is empty for enrichment parse",
            retryable=False,
            provider=context.provider,
            parser_version="v2",
        )

    invoke_request = LlmInvokeRequest(
        task_name=task_name,
        system_prompt=(
            "Extract course and event semantics from academic calendar text. "
            "Return JSON with schema: "
            '{"course_parse":{"dept":string|null,"number":number|null,"suffix":string|null,"quarter":"WI"|"SP"|"SU"|"FA"|null,'
            '"year2":number|null,"confidence":number,"evidence":string},'
            '"event_parts":{"type":"exam"|"deadline"|"quiz"|"project"|"lecture"|"other"|null,'
            '"index":number|null,"qualifier":string|null,"confidence":number,"evidence":string},'
            '"link_signals":{"keywords":["exam"|"midterm"|"final"],"exam_sequence":number|null,'
            '"location_text":string|null,"instructor_hint":string|null}}. '
            "Do not infer missing fields aggressively; use null when uncertain. Evidence must be copied from input text."
        ),
        user_payload={
            "source_id": context.source_id,
            "provider": context.provider,
            "source_kind": context.source_kind,
            "source_canonical": {
                "source_title": source_title,
                "source_summary": source_summary,
                "location": source_location or None,
                "organizer": source_organizer or None,
            },
        },
        output_schema_name="EventEnrichmentResponse",
        output_schema_json=EventEnrichmentResponse.model_json_schema(),
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
            parsed = EventEnrichmentResponse.model_validate(invoke_result.json_object)
            return {
                "course_parse": parsed.course_parse.model_dump(),
                "event_parts": parsed.event_parts.model_dump(),
                "link_signals": parsed.link_signals.model_dump(),
            }, invoke_result.model
        except ValidationError as exc:
            if attempt < LLM_FORMAT_MAX_ATTEMPTS:
                logger.warning(
                    "calendar_v2.format_retry request_id=%s source_id=%s task_name=%s error_code=%s attempt=%s/%s",
                    context.request_id or "-",
                    context.source_id,
                    task_name,
                    CALENDAR_SCHEMA_INVALID_CODE,
                    attempt,
                    LLM_FORMAT_MAX_ATTEMPTS,
                )
                continue
            logger.warning(
                "calendar_v2.format_retry_exhausted request_id=%s source_id=%s task_name=%s error_code=%s attempt=%s/%s",
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
                parser_version="v2",
            ) from exc

    raise LlmParseError(
        code=CALENDAR_SCHEMA_INVALID_CODE,
        message="calendar llm parser returned no valid payload after retries",
        retryable=False,
        provider=context.provider,
        parser_version="v2",
    )


# Kept import name stable for existing callers/tests.
parse_event_enrichment_text = parse_course_parse_text


def _map_llm_error(exc: LlmGatewayError, *, provider: str) -> LlmParseError:
    if exc.code == "parse_llm_timeout":
        return LlmParseError(
            code="parse_llm_timeout",
            message=str(exc),
            retryable=True,
            provider=provider,
            parser_version="v2",
        )
    if exc.code == "parse_llm_empty_output":
        return LlmParseError(
            code="parse_llm_empty_output",
            message=str(exc),
            retryable=False,
            provider=provider,
            parser_version="v2",
        )
    if exc.code == "parse_llm_schema_invalid":
        return LlmParseError(
            code=CALENDAR_SCHEMA_INVALID_CODE,
            message=str(exc),
            retryable=False,
            provider=provider,
            parser_version="v2",
        )
    if exc.code == "parse_llm_upstream_error":
        return LlmParseError(
            code=CALENDAR_UPSTREAM_ERROR_CODE,
            message=str(exc),
            retryable=exc.retryable,
            provider=provider,
            parser_version="v2",
        )
    return LlmParseError(
        code=exc.code,
        message=str(exc),
        retryable=exc.retryable,
        provider=provider,
        parser_version="v2",
    )


def _extract_source_canonical(*, component, source_id: int, index: int) -> dict:  # noqa: ANN001
    uid = _normalize_text(component.get("UID")) or f"calendar-{source_id}-{index}"
    recurrence_id = _normalize_ical_value(component.get("RECURRENCE-ID"))
    external_event_id = build_external_event_id(uid=uid, recurrence_id=recurrence_id)

    summary = _normalize_text(component.get("SUMMARY"))
    source_title = (summary or "Untitled")[:512]

    start_at = _normalize_datetime(component.get("DTSTART"))
    due_at = _normalize_datetime(component.get("DUE"))
    end_at = _normalize_datetime(component.get("DTEND"))

    if start_at is None and due_at is None:
        raise LlmParseError(
            code="llm_calendar_payload_invalid",
            message=f"calendar event {external_event_id} missing DTSTART/DUE",
            retryable=False,
            provider="calendar",
            parser_version="v2",
        )
    effective_start = start_at or due_at
    assert effective_start is not None
    effective_end = end_at or (effective_start + timedelta(hours=1))
    if effective_end <= effective_start:
        effective_end = effective_start + timedelta(hours=1)

    status = (_normalize_text(component.get("STATUS")) or "").upper() or None
    location = _normalize_text(component.get("LOCATION"))
    organizer = _normalize_text(component.get("ORGANIZER"))

    return {
        "external_event_id": external_event_id,
        "component_uid": uid,
        "component_recurrence_id": recurrence_id,
        "source_title": source_title,
        "source_summary": summary,
        "source_dtstart_utc": effective_start.isoformat(),
        "source_dtend_utc": effective_end.isoformat(),
        "status": status,
        "location": location,
        "organizer": organizer,
    }


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _normalize_ical_value(value: object) -> str | None:
    if value is None:
        return None
    candidate = value.dt if hasattr(value, "dt") else value
    if isinstance(candidate, datetime):
        if candidate.tzinfo is None:
            return candidate.replace(tzinfo=timezone.utc).isoformat()
        return candidate.astimezone(timezone.utc).isoformat()
    if isinstance(candidate, date):
        return candidate.isoformat()
    cleaned = str(candidate).strip()
    return cleaned or None


def _normalize_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    candidate = value.dt if hasattr(value, "dt") else value
    if isinstance(candidate, datetime):
        if candidate.tzinfo is None:
            return candidate.replace(tzinfo=timezone.utc)
        return candidate.astimezone(timezone.utc)
    if isinstance(candidate, date):
        return datetime(candidate.year, candidate.month, candidate.day, tzinfo=timezone.utc)
    text = str(candidate).strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
