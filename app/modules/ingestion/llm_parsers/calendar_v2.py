from __future__ import annotations

import logging

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.modules.ingestion.llm_parsers.contracts import LlmParseError, ParserContext, ParserOutput
from app.modules.ingestion.llm_parsers.schemas import CalendarParserResponse
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
    parser_name = "calendar_v2_llm"
    text = content.decode("utf-8", errors="replace").strip()
    if not text:
        raise LlmParseError(
            code="parse_llm_empty_output",
            message="calendar source content is empty after decode",
            retryable=False,
            provider=context.provider,
            parser_version="v2",
        )

    invoke_request = LlmInvokeRequest(
        task_name="calendar_event_extract",
        system_prompt=(
            "You extract structured calendar events from ICS text for a deadline tracking pipeline. "
            "Respond with JSON only using schema: "
            "{\"events\":[{\"uid\":string|null,\"title\":string,\"start_at\":string,\"end_at\":string,"
            "\"course_label\":string|null,\"raw_confidence\":number}]} . "
            "Return an empty events list when no actionable event can be extracted."
        ),
        user_payload={
            "source_id": context.source_id,
            "provider": context.provider,
            "source_kind": context.source_kind,
            "ics_text": text,
        },
        output_schema_name="CalendarParserResponse",
        output_schema_json=CalendarParserResponse.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
    )

    parsed: CalendarParserResponse | None = None
    invoke_result = None
    for attempt in range(1, LLM_FORMAT_MAX_ATTEMPTS + 1):
        try:
            invoke_result = invoke_llm_json(
                db,
                invoke_request=invoke_request,
            )
        except LlmGatewayError as exc:
            raise _map_llm_error(exc, provider=context.provider) from exc

        try:
            parsed = CalendarParserResponse.model_validate(invoke_result.json_object)
            break
        except ValidationError as exc:
            if attempt < LLM_FORMAT_MAX_ATTEMPTS:
                logger.warning(
                    "calendar_v2.format_retry request_id=%s source_id=%s task_name=calendar_event_extract "
                    "error_code=%s attempt=%s/%s",
                    context.request_id or "-",
                    context.source_id,
                    CALENDAR_SCHEMA_INVALID_CODE,
                    attempt,
                    LLM_FORMAT_MAX_ATTEMPTS,
                )
                continue
            logger.warning(
                "calendar_v2.format_retry_exhausted request_id=%s source_id=%s task_name=calendar_event_extract "
                "error_code=%s attempt=%s/%s",
                context.request_id or "-",
                context.source_id,
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

    if parsed is None or invoke_result is None:
        raise LlmParseError(
            code=CALENDAR_SCHEMA_INVALID_CODE,
            message="calendar llm parser returned no valid payload after retries",
            retryable=False,
            provider=context.provider,
            parser_version="v2",
        )

    records: list[dict] = []
    for index, event in enumerate(parsed.events):
        records.append(
            {
                "record_type": "calendar.event.extracted",
                "payload": {
                    "uid": event.uid or f"calendar-{context.source_id}-{index}",
                    "title": event.title,
                    "start_at": event.start_at,
                    "end_at": event.end_at,
                    "course_label": event.course_label,
                    "raw_confidence": float(event.raw_confidence),
                },
            }
        )

    return ParserOutput(
        records=records,
        parser_name=parser_name,
        parser_version="v2",
        model_hint=invoke_result.model,
    )


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
