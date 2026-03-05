from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.modules.ingestion.llm_parsers.contracts import LlmParseError, ParserContext, ParserOutput
from app.modules.ingestion.llm_parsers.schemas import GmailParserResponse
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

    invoke_request = LlmInvokeRequest(
        task_name="gmail_message_extract",
        system_prompt=(
            "You extract actionable event metadata from Gmail messages for a deadline tracker. "
            "Respond with JSON only using schema: "
            "{\"messages\":[{\"message_id\":string|null,"
            "\"due_at\":string|null,"
            "\"time_anchor_confidence\":number,"
            "\"course_parse\":{\"dept\":string|null,\"number\":number|null,\"suffix\":string|null,"
            "\"quarter\":\"WI\"|\"SP\"|\"SU\"|\"FA\"|null,\"year2\":number|null,\"confidence\":number,\"evidence\":string},"
            "\"event_parts\":{\"type\":\"exam\"|\"deadline\"|\"quiz\"|\"project\"|\"lecture\"|\"other\"|null,"
            "\"index\":number|null,\"qualifier\":string|null,\"confidence\":number,\"evidence\":string},"
            "\"link_signals\":{\"keywords\":[\"exam\"|\"midterm\"|\"final\"],\"exam_sequence\":number|null,"
            "\"location_text\":string|null,\"instructor_hint\":string|null}}]} . "
            "Return empty messages array when no extraction is possible."
        ),
        user_payload={
            "source_id": context.source_id,
            "provider": context.provider,
            "source_kind": context.source_kind,
            "message": payload,
        },
        output_schema_name="GmailParserResponse",
        output_schema_json=GmailParserResponse.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
    )

    parsed: GmailParserResponse | None = None
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
            parsed = GmailParserResponse.model_validate(invoke_result.json_object)
            break
        except ValidationError as exc:
            if attempt < LLM_FORMAT_MAX_ATTEMPTS:
                logger.warning(
                    "gmail_parser.format_retry request_id=%s source_id=%s task_name=gmail_message_extract "
                    "error_code=%s attempt=%s/%s",
                    context.request_id or "-",
                    context.source_id,
                    GMAIL_SCHEMA_INVALID_CODE,
                    attempt,
                    LLM_FORMAT_MAX_ATTEMPTS,
                )
                continue
            logger.warning(
                "gmail_parser.format_retry_exhausted request_id=%s source_id=%s task_name=gmail_message_extract "
                "error_code=%s attempt=%s/%s",
                context.request_id or "-",
                context.source_id,
                GMAIL_SCHEMA_INVALID_CODE,
                attempt,
                LLM_FORMAT_MAX_ATTEMPTS,
            )
            raise LlmParseError(
                code=GMAIL_SCHEMA_INVALID_CODE,
                message=f"gmail llm schema invalid: {exc.errors()}",
                retryable=False,
                provider=context.provider,
                parser_version="mainline",
            ) from exc

    if parsed is None or invoke_result is None:
        raise LlmParseError(
            code=GMAIL_SCHEMA_INVALID_CODE,
            message="gmail llm parser returned no valid payload after retries",
            retryable=False,
            provider=context.provider,
            parser_version="mainline",
        )

    source_message_id = payload.get("message_id") if isinstance(payload.get("message_id"), str) else None
    source_subject = payload.get("subject") if isinstance(payload.get("subject"), str) else "Untitled"
    source_snippet = payload.get("snippet") if isinstance(payload.get("snippet"), str) else None
    source_from_header = payload.get("from_header") if isinstance(payload.get("from_header"), str) else None
    source_thread_id = payload.get("thread_id") if isinstance(payload.get("thread_id"), str) else None
    source_internal_date = payload.get("internal_date") if isinstance(payload.get("internal_date"), str) else None

    records: list[dict] = []
    for index, message in enumerate(parsed.messages):
        message_id = message.message_id or source_message_id or f"gmail-{context.source_id}-{index}"
        due_at = _parse_optional_iso_datetime(message.due_at)
        due_iso = due_at.isoformat() if due_at is not None else None
        end_iso = (due_at + timedelta(hours=1)).isoformat() if due_at is not None else None
        course_parse = message.course_parse.model_dump()
        event_parts = message.event_parts.model_dump()
        link_signals = message.link_signals.model_dump()
        confidence = float(message.time_anchor_confidence)
        records.append(
            {
                "record_type": "gmail.message.extracted",
                "payload": {
                    "message_id": message_id,
                    "source_canonical": {
                        "external_event_id": message_id,
                        "source_title": source_subject[:512] if isinstance(source_subject, str) else "Untitled",
                        "source_summary": source_snippet,
                        "source_dtstart_utc": due_iso,
                        "source_dtend_utc": end_iso,
                        "time_anchor_confidence": confidence,
                        "from_header": source_from_header,
                        "thread_id": source_thread_id,
                        "internal_date": source_internal_date,
                    },
                    "enrichment": {
                        "course_parse": course_parse,
                        "event_parts": event_parts,
                        "link_signals": link_signals,
                        "payload_schema_version": "obs_v3",
                    },
                },
            }
        )

    return ParserOutput(
        records=records,
        parser_name=parser_name,
        parser_version="mainline",
        model_hint=invoke_result.model,
    )


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


def _parse_optional_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
