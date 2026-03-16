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
    if isinstance(invoke_request.cache_prefix_payload, dict):
        return {
            "model": profile.model,
            "temperature": invoke_request.temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": _build_constant_system_prompt(),
                },
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": _build_cache_prefix(
                                invoke_request=invoke_request,
                                profile=profile,
                            ),
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": _build_task_prompt(
                        invoke_request=invoke_request,
                        input_json=truncated_input_json,
                    ),
                },
            ],
        }
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
) -> tuple[dict, dict, str | None]:
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
    return payload, usage, None


def _build_system_prompt(*, invoke_request: LlmInvokeRequest) -> str:
    return (
        f"{invoke_request.system_prompt.strip()}\n\n"
        "You must return one JSON object only. Do not output markdown, code fences, or prose.\n"
        f"Output schema name: {invoke_request.output_schema_name}\n"
        "Schema JSON:\n"
        f"{json.dumps(invoke_request.output_schema_json, ensure_ascii=True)}"
    )


def _build_constant_system_prompt() -> str:
    return "You must return one JSON object only. Do not output markdown, code fences, or prose."


def _build_cache_prefix(*, invoke_request: LlmInvokeRequest, profile: ResolvedLlmProfile) -> str:
    payload = _truncate_prefix_payload(
        payload=invoke_request.cache_prefix_payload or {},
        max_chars=profile.max_input_chars,
    )
    return "\n".join(
        [
            "SOURCE_PREFIX_JSON:",
            payload,
        ]
    )


def _build_task_prompt(*, invoke_request: LlmInvokeRequest, input_json: str) -> str:
    return "\n".join(
        [
            "TASK_INSTRUCTIONS:",
            invoke_request.system_prompt.strip(),
            f"Output schema name: {invoke_request.output_schema_name}",
            "Schema JSON:",
            json.dumps(invoke_request.output_schema_json, ensure_ascii=True),
            "TASK_INPUT_JSON:",
            input_json,
        ]
    )


def _build_user_prompt(*, invoke_request: LlmInvokeRequest, input_json: str) -> str:
    if isinstance(invoke_request.shared_user_payload, dict):
        return "\n".join(
            [
                "INPUT_JSON:",
                json.dumps(
                    {
                        "message_context": invoke_request.shared_user_payload,
                        "task_input": invoke_request.user_payload,
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
            ]
        )
    lines = [
        f"TASK: {invoke_request.task_name}",
        "INPUT_JSON:",
        input_json,
    ]
    return "\n".join(lines)


def _truncate_prefix_payload(*, payload: dict, max_chars: int) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    if max_chars <= 0 or len(serialized) <= max_chars:
        return serialized
    if max_chars <= 64:
        return serialized[:max_chars]
    head = max_chars // 2
    tail = max_chars - head - 1
    return f"{serialized[:head]}\n{serialized[-tail:]}"


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
