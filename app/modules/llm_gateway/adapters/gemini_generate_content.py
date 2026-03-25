from __future__ import annotations

import json

from app.modules.llm_gateway.contracts import (
    LlmGatewayError,
    LlmInvokeRequest,
    LlmProtocolLiteral,
    LlmStreamRequest,
    ResolvedLlmProfile,
)
from app.modules.llm_gateway.json_contract import parse_json_object_from_text


def build_gemini_generate_content_payload(
    *,
    invoke_request: LlmInvokeRequest,
    profile: ResolvedLlmProfile,
    truncated_input_json: str,
) -> dict:
    return {
        "systemInstruction": {"parts": [{"text": _build_system_prompt(invoke_request=invoke_request)}]},
        "contents": [{"role": "user", "parts": [{"text": _build_user_prompt(invoke_request=invoke_request, input_json=truncated_input_json)}]}],
        "generationConfig": {
            "temperature": invoke_request.temperature,
            "responseMimeType": "application/json",
            "responseJsonSchema": invoke_request.output_schema_json,
        },
    }


def build_gemini_stream_payload(
    *,
    stream_request: LlmStreamRequest,
    profile: ResolvedLlmProfile,
) -> dict:
    return {
        "systemInstruction": {"parts": [{"text": stream_request.system_prompt.strip()}]},
        "contents": [{"role": "user", "parts": [{"text": _build_stream_user_prompt(stream_request=stream_request)}]}],
        "generationConfig": {
            "temperature": stream_request.temperature,
            "responseMimeType": "text/plain",
        },
    }


def extract_gemini_generate_content_json(
    *,
    response_json: dict,
    provider_id: str,
    protocol: LlmProtocolLiteral,
) -> tuple[dict, dict, str | None]:
    if isinstance(response_json.get("error"), dict):
        message = str((response_json.get("error") or {}).get("message") or "gemini api returned error")
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message=message,
            retryable=False,
            provider_id=provider_id,
            protocol=protocol,
        )

    raw_text = extract_gemini_text(response_json=response_json)
    payload = parse_json_object_from_text(
        raw_text=raw_text,
        provider_id=provider_id,
        protocol=protocol,
    )
    usage = response_json.get("usageMetadata")
    if not isinstance(usage, dict):
        usage = {}
    response_id = response_json.get("responseId") or response_json.get("response_id")
    response_id_text = response_id.strip() if isinstance(response_id, str) and response_id.strip() else None
    return payload, usage, response_id_text


def extract_gemini_text(*, response_json: dict) -> str:
    candidates = response_json.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("gemini response missing candidates")
    chunks: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text)
    cleaned = "".join(chunks).strip()
    if cleaned:
        return cleaned
    raise ValueError("gemini content is empty")


def _build_system_prompt(*, invoke_request: LlmInvokeRequest) -> str:
    return (
        f"{invoke_request.system_prompt.strip()}\n\n"
        "You must return one JSON object only. Do not output markdown, code fences, or prose.\n"
        f"Output schema name: {invoke_request.output_schema_name}\n"
        "Schema JSON:\n"
        f"{json.dumps(invoke_request.output_schema_json, ensure_ascii=True)}"
    )


def _build_user_prompt(*, invoke_request: LlmInvokeRequest, input_json: str) -> str:
    if isinstance(invoke_request.shared_user_payload, dict):
        return json.dumps(
            {
                "message_context": invoke_request.shared_user_payload,
                "task_input": invoke_request.user_payload,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
    return "\n".join(
        [
            f"TASK: {invoke_request.task_name}",
            "INPUT_JSON:",
            input_json,
        ]
    )


def _build_stream_user_prompt(*, stream_request: LlmStreamRequest) -> str:
    if isinstance(stream_request.shared_user_payload, dict):
        return json.dumps(
            {
                "message_context": stream_request.shared_user_payload,
                "task_input": stream_request.user_payload,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
    return json.dumps(stream_request.user_payload, ensure_ascii=True, separators=(",", ":"))


__all__ = [
    "build_gemini_generate_content_payload",
    "build_gemini_stream_payload",
    "extract_gemini_generate_content_json",
    "extract_gemini_text",
]
