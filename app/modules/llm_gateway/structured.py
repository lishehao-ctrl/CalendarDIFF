from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.modules.llm_gateway.contracts import LlmGatewayError, LlmInvokeRequest, LlmInvokeResult
from app.modules.llm_gateway.gateway import invoke_llm_json
from app.modules.llm_gateway.retry_policy import LLM_FORMAT_MAX_ATTEMPTS

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class LlmTypedInvokeResult:
    value: BaseModel
    invoke_result: LlmInvokeResult


def invoke_llm_typed(
    db: Session,
    *,
    invoke_request: LlmInvokeRequest,
    response_model: type[ModelT],
    validation_label: str | None = None,
    invoke_json_fn: Callable[[Session, LlmInvokeRequest], LlmInvokeResult] | None = None,
) -> LlmTypedInvokeResult:
    label = validation_label or invoke_request.task_name
    invoke_json = invoke_json_fn or _invoke_llm_json_adapter

    for attempt in range(1, LLM_FORMAT_MAX_ATTEMPTS + 1):
        invoke_result = invoke_json(db, invoke_request)
        try:
            parsed = response_model.model_validate(invoke_result.json_object)
        except ValidationError as exc:
            if attempt < LLM_FORMAT_MAX_ATTEMPTS:
                logger.warning(
                    "llm_gateway.typed_validation_retry request_id=%s source_id=%s task_name=%s label=%s "
                    "error_code=parse_llm_schema_invalid attempt=%s/%s",
                    invoke_request.request_id or "-",
                    invoke_request.source_id if invoke_request.source_id is not None else "-",
                    invoke_request.task_name,
                    label,
                    attempt,
                    LLM_FORMAT_MAX_ATTEMPTS,
                )
                continue
            logger.warning(
                "llm_gateway.typed_validation_retry_exhausted request_id=%s source_id=%s task_name=%s label=%s "
                "error_code=parse_llm_schema_invalid attempt=%s/%s",
                invoke_request.request_id or "-",
                invoke_request.source_id if invoke_request.source_id is not None else "-",
                invoke_request.task_name,
                label,
                attempt,
                LLM_FORMAT_MAX_ATTEMPTS,
            )
            raise LlmGatewayError(
                code="parse_llm_schema_invalid",
                message=f"{label} validation failed: {exc.errors()}",
                retryable=False,
                provider_id=invoke_result.provider_id,
                protocol=invoke_result.protocol,
            ) from exc
        return LlmTypedInvokeResult(value=parsed, invoke_result=invoke_result)

    raise RuntimeError("unreachable: typed llm invoke retry loop exhausted without returning")


def _invoke_llm_json_adapter(db: Session, invoke_request: LlmInvokeRequest) -> LlmInvokeResult:
    return invoke_llm_json(db, invoke_request=invoke_request)


__all__ = [
    "LlmTypedInvokeResult",
    "invoke_llm_typed",
]
