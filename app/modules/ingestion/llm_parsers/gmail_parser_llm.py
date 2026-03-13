from __future__ import annotations

import logging
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.modules.ingestion.llm_parsers.contracts import LlmParseError, ParserContext
from app.modules.llm_gateway import (
    LLM_FORMAT_MAX_ATTEMPTS,
    LlmGatewayError,
    LlmInvokeRequest,
    LlmInvokeResult,
)

GMAIL_SCHEMA_INVALID_CODE = "parse_llm_gmail_schema_invalid"
GMAIL_UPSTREAM_ERROR_CODE = "parse_llm_gmail_upstream_error"

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)


class LlmInvokeCallable(Protocol):
    def __call__(self, db: Session, *, invoke_request: LlmInvokeRequest) -> LlmInvokeResult:
        ...


def invoke_schema_validated(
    *,
    db: Session,
    context: ParserContext,
    invoke_request: LlmInvokeRequest,
    response_model: type[ModelT],
    stage_label: str,
    invoke_json: LlmInvokeCallable,
) -> tuple[ModelT, str | None]:
    parsed: ModelT | None = None
    invoke_result: LlmInvokeResult | None = None

    for attempt in range(1, LLM_FORMAT_MAX_ATTEMPTS + 1):
        try:
            invoke_result = invoke_json(db, invoke_request=invoke_request)
        except LlmGatewayError as exc:
            raise map_llm_error(exc, provider=context.provider) from exc

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


def map_llm_error(exc: LlmGatewayError, *, provider: str) -> LlmParseError:
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


__all__ = [
    "GMAIL_SCHEMA_INVALID_CODE",
    "GMAIL_UPSTREAM_ERROR_CODE",
    "LlmInvokeCallable",
    "invoke_schema_validated",
    "map_llm_error",
]
