from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.modules.runtime.connectors.llm_parsers.contracts import LlmParseError, ParserContext
from app.modules.llm_gateway import (
    LlmGatewayError,
    LlmInvokeRequest,
    LlmInvokeResult,
    invoke_llm_typed,
)

GMAIL_SCHEMA_INVALID_CODE = "parse_llm_gmail_schema_invalid"
GMAIL_UPSTREAM_ERROR_CODE = "parse_llm_gmail_upstream_error"
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
    try:
        typed_result = invoke_llm_typed(
            db,
            invoke_request=invoke_request,
            response_model=response_model,
            validation_label=stage_label,
            invoke_json_fn=lambda db_session, request: invoke_json(db_session, invoke_request=request),
        )
    except LlmGatewayError as exc:
        raise map_llm_error(exc, provider=context.provider) from exc

    parsed = typed_result.value
    assert isinstance(parsed, response_model)
    invoke_result = typed_result.invoke_result
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
