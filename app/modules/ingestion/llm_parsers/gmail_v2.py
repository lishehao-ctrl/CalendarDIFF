from __future__ import annotations

import json

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.modules.ingestion.llm_parsers.contracts import LlmParseError, ParserContext, ParserOutput
from app.modules.ingestion.llm_parsers.schemas import GmailParserResponse
from app.modules.llm_gateway import LlmGatewayError, LlmInvokeRequest, invoke_llm_json

GMAIL_SCHEMA_INVALID_CODE = "parse_llm_gmail_schema_invalid"
GMAIL_UPSTREAM_ERROR_CODE = "parse_llm_gmail_upstream_error"


def parse_gmail_payload(*, db: Session, payload: dict, context: ParserContext) -> ParserOutput:
    parser_name = "gmail_v2_llm"
    serialized_payload = json.dumps(payload, ensure_ascii=True)
    if not serialized_payload:
        raise LlmParseError(
            code="parse_llm_empty_output",
            message="gmail payload is empty",
            retryable=False,
            provider=context.provider,
            parser_version="v2",
        )

    try:
        invoke_result = invoke_llm_json(
            db,
            invoke_request=LlmInvokeRequest(
                task_name="gmail_message_extract",
                system_prompt=(
                    "You extract actionable event metadata from Gmail messages for a deadline tracker. "
                    "Respond with JSON only using schema: "
                    "{\"messages\":[{\"message_id\":string|null,\"subject\":string|null,"
                    "\"event_type\":\"deadline\"|\"exam\"|\"schedule_change\"|\"assignment\"|"
                    "\"action_required\"|\"announcement\"|\"grade\"|\"other\"|null,"
                    "\"due_at\":string|null,\"confidence\":number,\"raw_extract\":object}]} . "
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
            ),
        )
    except LlmGatewayError as exc:
        raise _map_llm_error(exc, provider=context.provider) from exc

    try:
        parsed = GmailParserResponse.model_validate(invoke_result.json_object)
    except ValidationError as exc:
        raise LlmParseError(
            code=GMAIL_SCHEMA_INVALID_CODE,
            message=f"gmail llm schema invalid: {exc.errors()}",
            retryable=False,
            provider=context.provider,
            parser_version="v2",
        ) from exc

    source_message_id = payload.get("message_id") if isinstance(payload.get("message_id"), str) else None
    source_subject = payload.get("subject") if isinstance(payload.get("subject"), str) else None

    records: list[dict] = []
    for index, message in enumerate(parsed.messages):
        message_id = message.message_id or source_message_id or f"gmail-{context.source_id}-{index}"
        subject = message.subject or source_subject
        records.append(
            {
                "record_type": "gmail.message.extracted",
                "payload": {
                    "message_id": message_id,
                    "subject": subject,
                    "event_type": message.event_type,
                    "due_at": message.due_at,
                    "confidence": float(message.confidence),
                    "raw_extract": dict(message.raw_extract),
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
            code=GMAIL_SCHEMA_INVALID_CODE,
            message=str(exc),
            retryable=False,
            provider=provider,
            parser_version="v2",
        )
    if exc.code == "parse_llm_upstream_error":
        return LlmParseError(
            code=GMAIL_UPSTREAM_ERROR_CODE,
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
