from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.modules.llm_gateway.adapters.chat_completions import (
    build_chat_completions_payload,
    extract_chat_completions_json,
)
from app.modules.llm_gateway.contracts import (
    LlmApiModeLiteral,
    LlmGatewayError,
    LlmInvokeRequest,
    LlmInvokeResult,
    ResolvedLlmProfile,
)
from app.modules.llm_gateway.json_contract import truncate_user_payload, validate_schema
from app.modules.llm_gateway.registry import resolve_llm_profile
from app.modules.llm_gateway.retry_policy import LLM_FORMAT_MAX_ATTEMPTS, is_format_retryable_code
from app.modules.llm_gateway.transport_openai_compat import OpenAICompatTransport

logger = logging.getLogger(__name__)


class LlmGateway:
    def __init__(self, *, transport: OpenAICompatTransport | None = None) -> None:
        self._transport = transport or OpenAICompatTransport()

    def invoke_json(self, db: Session, *, invoke_request: LlmInvokeRequest) -> LlmInvokeResult:
        provider_id = "-"
        model = "-"

        try:
            profile = resolve_llm_profile(
                db,
                source_id=invoke_request.source_id,
            )
            provider_id = profile.provider_id
            model = profile.model
        except LlmGatewayError as exc:
            logger.warning(
                "llm_gateway.invoke_json failed request_id=%s source_id=%s task_name=%s provider_id=%s model=%s "
                "latency_ms=- error_code=%s retryable=%s http_status=%s",
                invoke_request.request_id or "-",
                invoke_request.source_id if invoke_request.source_id is not None else "-",
                invoke_request.task_name,
                exc.provider_id or provider_id,
                model,
                exc.code,
                exc.retryable,
                exc.http_status if exc.http_status is not None else "-",
            )
            raise

        for attempt in range(1, LLM_FORMAT_MAX_ATTEMPTS + 1):
            try:
                result = self._invoke_json_once(
                    profile=profile,
                    invoke_request=invoke_request,
                )
                logger.info(
                    "llm_gateway.invoke_json ok request_id=%s source_id=%s task_name=%s provider_id=%s model=%s "
                    "latency_ms=%s error_code=- retryable=- http_status=- attempt=%s/%s",
                    invoke_request.request_id or "-",
                    invoke_request.source_id if invoke_request.source_id is not None else "-",
                    invoke_request.task_name,
                    result.provider_id,
                    result.model,
                    result.latency_ms,
                    attempt,
                    LLM_FORMAT_MAX_ATTEMPTS,
                )
                return result
            except LlmGatewayError as exc:
                if is_format_retryable_code(exc.code) and attempt < LLM_FORMAT_MAX_ATTEMPTS:
                    logger.warning(
                        "llm_gateway.invoke_json format_retry request_id=%s source_id=%s task_name=%s provider_id=%s "
                        "model=%s error_code=%s attempt=%s/%s",
                        invoke_request.request_id or "-",
                        invoke_request.source_id if invoke_request.source_id is not None else "-",
                        invoke_request.task_name,
                        exc.provider_id or provider_id,
                        model,
                        exc.code,
                        attempt,
                        LLM_FORMAT_MAX_ATTEMPTS,
                    )
                    continue
                if is_format_retryable_code(exc.code):
                    logger.warning(
                        "llm_gateway.invoke_json format_retry_exhausted request_id=%s source_id=%s task_name=%s "
                        "provider_id=%s model=%s error_code=%s attempt=%s/%s",
                        invoke_request.request_id or "-",
                        invoke_request.source_id if invoke_request.source_id is not None else "-",
                        invoke_request.task_name,
                        exc.provider_id or provider_id,
                        model,
                        exc.code,
                        attempt,
                        LLM_FORMAT_MAX_ATTEMPTS,
                    )
                logger.warning(
                    "llm_gateway.invoke_json failed request_id=%s source_id=%s task_name=%s provider_id=%s model=%s "
                    "latency_ms=- error_code=%s retryable=%s http_status=%s attempt=%s/%s",
                    invoke_request.request_id or "-",
                    invoke_request.source_id if invoke_request.source_id is not None else "-",
                    invoke_request.task_name,
                    exc.provider_id or provider_id,
                    model,
                    exc.code,
                    exc.retryable,
                    exc.http_status if exc.http_status is not None else "-",
                    attempt,
                    LLM_FORMAT_MAX_ATTEMPTS,
                )
                raise
        raise RuntimeError("unreachable: llm invoke retry loop exhausted without returning")

    def _invoke_json_once(
        self,
        *,
        profile: ResolvedLlmProfile,
        invoke_request: LlmInvokeRequest,
    ) -> LlmInvokeResult:
        truncated_input_json = truncate_user_payload(
            user_payload=invoke_request.user_payload,
            profile=profile,
        )
        request_payload = build_chat_completions_payload(
            invoke_request=invoke_request,
            profile=profile,
            truncated_input_json=truncated_input_json,
        )
        response_json, latency_ms, upstream_request_id = self._transport.post_json(
            profile=profile,
            payload=request_payload,
            request_context={
                "request_id": invoke_request.request_id or "-",
                "source_id": invoke_request.source_id if invoke_request.source_id is not None else "-",
                "task_name": invoke_request.task_name,
                "model": profile.model,
                "provider_id": profile.provider_id,
            },
        )
        extracted_json, raw_usage = _extract_chat_result(
            response_json=response_json,
            provider_id=profile.provider_id,
            api_mode=profile.api_mode,
        )

        validate_schema(
            payload=extracted_json,
            schema=invoke_request.output_schema_json,
            schema_name=invoke_request.output_schema_name,
            provider_id=profile.provider_id,
            api_mode=profile.api_mode,
        )

        return LlmInvokeResult(
            json_object=extracted_json,
            provider_id=profile.provider_id,
            model=profile.model,
            api_mode=profile.api_mode,
            latency_ms=latency_ms,
            upstream_request_id=upstream_request_id,
            raw_usage=raw_usage,
        )


_GLOBAL_GATEWAY = LlmGateway()


def invoke_llm_json(db: Session, *, invoke_request: LlmInvokeRequest) -> LlmInvokeResult:
    return _GLOBAL_GATEWAY.invoke_json(db, invoke_request=invoke_request)


def _extract_chat_result(
    *,
    response_json: dict,
    provider_id: str,
    api_mode: LlmApiModeLiteral,
) -> tuple[dict, dict]:
    try:
        return extract_chat_completions_json(
            response_json=response_json,
            provider_id=provider_id,
            api_mode=api_mode,
        )
    except ValueError as exc:
        message = str(exc).lower()
        if "empty" in message:
            raise LlmGatewayError(
                code="parse_llm_empty_output",
                message=str(exc),
                retryable=False,
                provider_id=provider_id,
                api_mode=api_mode,
            ) from exc
        raise LlmGatewayError(
            code="parse_llm_schema_invalid",
            message=str(exc),
            retryable=False,
            provider_id=provider_id,
            api_mode=api_mode,
        ) from exc
