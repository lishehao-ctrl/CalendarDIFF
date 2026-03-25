from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

from app.modules.llm_gateway.contracts import LlmGatewayError, LlmProtocolLiteral, ResolvedLlmProfile


def truncate_user_payload(*, user_payload: dict, profile: ResolvedLlmProfile) -> str:
    serialized = json.dumps(user_payload, ensure_ascii=True, separators=(",", ":"))
    max_chars = max(int(profile.max_input_chars), 0)
    if max_chars <= 0 or len(serialized) <= max_chars:
        return serialized
    if max_chars <= 64:
        return serialized[:max_chars]
    head = max_chars // 2
    tail = max_chars - head - 1
    return f"{serialized[:head]}\n{serialized[-tail:]}"


def ensure_json_object(*, payload: Any, provider_id: str, protocol: LlmProtocolLiteral | None) -> dict:
    if not isinstance(payload, dict):
        raise LlmGatewayError(
            code="parse_llm_schema_invalid",
            message="llm output root must be a json object",
            retryable=False,
            provider_id=provider_id,
            protocol=protocol,
        )
    return payload


def parse_json_object_from_text(*, raw_text: str, provider_id: str, protocol: LlmProtocolLiteral | None) -> dict:
    text = raw_text.strip()
    if not text:
        raise LlmGatewayError(
            code="parse_llm_empty_output",
            message="llm output text is empty",
            retryable=False,
            provider_id=provider_id,
            protocol=protocol,
        )
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise LlmGatewayError(
                    code="parse_llm_schema_invalid",
                    message="llm output is not valid json object",
                    retryable=False,
                    provider_id=provider_id,
                    protocol=protocol,
                ) from exc
        else:
            raise LlmGatewayError(
                code="parse_llm_schema_invalid",
                message="llm output is not valid json object",
                retryable=False,
                provider_id=provider_id,
                protocol=protocol,
            )
    return ensure_json_object(payload=parsed, provider_id=provider_id, protocol=protocol)


def validate_schema(
    *,
    payload: dict,
    schema: dict,
    schema_name: str,
    provider_id: str,
    protocol: LlmProtocolLiteral | None,
) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.absolute_path))
    if not errors:
        return
    brief = "; ".join(err.message for err in errors[:3])
    raise LlmGatewayError(
        code="parse_llm_schema_invalid",
        message=f"{schema_name} validation failed: {brief}",
        retryable=False,
        provider_id=provider_id,
        protocol=protocol,
    )
