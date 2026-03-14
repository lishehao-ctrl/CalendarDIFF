from __future__ import annotations

import json

from app.modules.llm_gateway.contracts import (
    LlmApiModeLiteral,
    LlmGatewayError,
    LlmInvokeRequest,
    ResolvedLlmProfile,
)
from app.modules.llm_gateway.json_contract import parse_json_object_from_text


def build_responses_payload(
    *,
    invoke_request: LlmInvokeRequest,
    profile: ResolvedLlmProfile,
    truncated_input_json: str,
) -> dict:
    return {
        "model": profile.model,
        "temperature": invoke_request.temperature,
        "instructions": _build_system_prompt(invoke_request=invoke_request),
        "input": _build_user_prompt(invoke_request=invoke_request, input_json=truncated_input_json),
        "text": {
            "format": {
                "type": "json_schema",
                "name": invoke_request.output_schema_name,
                "schema": invoke_request.output_schema_json,
                "strict": True,
            }
        },
    }


def extract_responses_json(
    *,
    response_json: dict,
    provider_id: str,
    api_mode: LlmApiModeLiteral,
) -> tuple[dict, dict]:
    error_payload = response_json.get("error")
    if isinstance(error_payload, dict):
        message = str(error_payload.get("message") or "responses api returned error")
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message=message,
            retryable=False,
            provider_id=provider_id,
            api_mode=api_mode,
        )

    output = response_json.get("output")
    if not isinstance(output, list) or not output:
        raise ValueError("responses output is empty")

    raw_text = _extract_output_text(output)
    payload = parse_json_object_from_text(
        raw_text=raw_text,
        provider_id=provider_id,
        api_mode=api_mode,
    )
    usage = response_json.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    return payload, usage


def _extract_output_text(output: list[object]) -> str:
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        content = item.get("content")
        text = _extract_message_content_text(content)
        if text:
            return text
    raise ValueError("responses message content is empty")


def _extract_message_content_text(content: object) -> str:
    if isinstance(content, str):
        cleaned = content.strip()
        if cleaned:
            return cleaned
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                chunks.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type not in {"output_text", "text"}:
                continue
            text_value = item.get("text")
            if isinstance(text_value, str) and text_value.strip():
                chunks.append(text_value.strip())
        if chunks:
            return "\n".join(chunks)
    return ""


def _build_system_prompt(*, invoke_request: LlmInvokeRequest) -> str:
    return (
        f"{invoke_request.system_prompt.strip()}\n\n"
        "You must return one JSON object only. Do not output markdown, code fences, or prose.\n"
        f"Output schema name: {invoke_request.output_schema_name}\n"
        "Schema JSON:\n"
        f"{json.dumps(invoke_request.output_schema_json, ensure_ascii=True)}"
    )


def _build_user_prompt(*, invoke_request: LlmInvokeRequest, input_json: str) -> str:
    lines = [
        f"TASK: {invoke_request.task_name}",
        f"REQUEST_ID: {invoke_request.request_id or 'n/a'}",
        f"SOURCE_ID: {invoke_request.source_id if invoke_request.source_id is not None else 'n/a'}",
        f"SOURCE_PROVIDER: {invoke_request.source_provider or 'n/a'}",
        "INPUT_JSON:",
        input_json,
    ]
    return "\n".join(lines)
