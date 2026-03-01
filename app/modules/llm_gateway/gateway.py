from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.llm_gateway.adapters.chat_completions import (
    build_chat_completions_payload,
    extract_chat_completions_json,
)
from app.modules.llm_gateway.adapters.responses import (
    build_responses_payload,
    extract_responses_json,
)
from app.modules.llm_gateway.contracts import (
    LlmApiModeLiteral,
    LlmGatewayError,
    LlmInvokeRequest,
    LlmInvokeResult,
)
from app.modules.llm_gateway.json_contract import truncate_user_payload, validate_schema
from app.modules.llm_gateway.registry import resolve_llm_profile
from app.modules.llm_gateway.transport_openai_compat import OpenAICompatTransport


class LlmGateway:
    def __init__(self, *, transport: OpenAICompatTransport | None = None) -> None:
        self._transport = transport or OpenAICompatTransport()

    def invoke_json(self, db: Session, *, invoke_request: LlmInvokeRequest) -> LlmInvokeResult:
        profile = resolve_llm_profile(
            db,
            source_id=invoke_request.source_id,
            explicit_provider_id=invoke_request.llm_provider_id,
        )
        truncated_input_json = truncate_user_payload(
            user_payload=invoke_request.user_payload,
            profile=profile,
        )
        if profile.api_mode == "chat_completions":
            request_payload = build_chat_completions_payload(
                invoke_request=invoke_request,
                profile=profile,
                truncated_input_json=truncated_input_json,
            )
            response_json, latency_ms, upstream_request_id = self._transport.post_json(
                profile=profile,
                payload=request_payload,
            )
            extracted_json, raw_usage = _extract_chat_result(
                response_json=response_json,
                provider_id=profile.provider_id,
                api_mode=profile.api_mode,
            )
        elif profile.api_mode == "responses":
            request_payload = build_responses_payload(
                invoke_request=invoke_request,
                profile=profile,
                truncated_input_json=truncated_input_json,
            )
            response_json, latency_ms, upstream_request_id = self._transport.post_json(
                profile=profile,
                payload=request_payload,
            )
            extracted_json, raw_usage = _extract_responses_result(
                response_json=response_json,
                provider_id=profile.provider_id,
                api_mode=profile.api_mode,
            )
        else:  # pragma: no cover - guarded by registry
            raise LlmGatewayError(
                code="parse_llm_mode_unsupported",
                message=f"unsupported llm api mode: {profile.api_mode}",
                retryable=False,
                provider_id=profile.provider_id,
                api_mode=None,
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


def _extract_responses_result(
    *,
    response_json: dict,
    provider_id: str,
    api_mode: LlmApiModeLiteral,
) -> tuple[dict, dict]:
    try:
        return extract_responses_json(
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
