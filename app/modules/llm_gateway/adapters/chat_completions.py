from __future__ import annotations

import json

from app.modules.llm_gateway.contracts import LlmApiModeLiteral, LlmInvokeRequest, ResolvedLlmProfile
from app.modules.llm_gateway.json_contract import parse_json_object_from_text


def build_chat_completions_payload(
    *,
    invoke_request: LlmInvokeRequest,
    profile: ResolvedLlmProfile,
    truncated_input_json: str,
) -> dict:
    return {
        "model": profile.model,
        "temperature": invoke_request.temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _build_system_prompt(invoke_request=invoke_request)},
            {"role": "user", "content": _build_user_prompt(invoke_request=invoke_request, input_json=truncated_input_json)},
        ],
    }


def extract_chat_completions_json(
    *,
    response_json: dict,
    provider_id: str,
    api_mode: LlmApiModeLiteral,
) -> tuple[dict, dict]:
    choices = response_json.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("chat completions response missing choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("chat completions first choice is invalid")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("chat completions message payload is invalid")

    raw_text = _extract_text_content(message.get("content"))
    payload = parse_json_object_from_text(
        raw_text=raw_text,
        provider_id=provider_id,
        api_mode=api_mode,
    )
    usage = response_json.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    return payload, usage


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


def _extract_text_content(content: object) -> str:
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
            for key in ("text", "output_text", "value"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    chunks.append(value.strip())
                    break
        if chunks:
            return "\n".join(chunks)
    raise ValueError("chat completions content is empty")
