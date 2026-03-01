from __future__ import annotations

import json
from typing import Any

from app.modules.llm_gateway.contracts import LlmApiModeLiteral, LlmInvokeRequest, ResolvedLlmProfile
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
        "store": False,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": _build_system_prompt(invoke_request=invoke_request)}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": _build_user_prompt(invoke_request=invoke_request, input_json=truncated_input_json)}],
            },
        ],
    }


def extract_responses_json(
    *,
    response_json: dict,
    provider_id: str,
    api_mode: LlmApiModeLiteral,
) -> tuple[dict, dict]:
    raw_text = extract_responses_text(response_json)
    payload = parse_json_object_from_text(
        raw_text=raw_text,
        provider_id=provider_id,
        api_mode=api_mode,
    )
    usage = response_json.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    return payload, usage


def extract_responses_text(response: Any) -> str:
    mapped = _as_mapping(response)
    if mapped:
        output_text = mapped.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()
        if isinstance(output_text, list):
            for item in output_text:
                if isinstance(item, str) and item.strip():
                    return item.strip()
        output_items = mapped.get("output")
        extracted = _extract_from_output_items(output_items)
        if extracted:
            return extracted
    raise ValueError("responses output is empty")


def _extract_from_output_items(output_items: Any) -> str | None:
    if not isinstance(output_items, list):
        return None
    for output_item in output_items:
        mapped = _as_mapping(output_item)
        if mapped is None:
            continue
        content = mapped.get("content")
        if isinstance(content, list):
            for content_item in content:
                extracted = _extract_text_from_content_item(content_item)
                if extracted:
                    return extracted
        for key in ("text", "output_text", "value"):
            value = mapped.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _extract_text_from_content_item(content_item: Any) -> str | None:
    if isinstance(content_item, str):
        cleaned = content_item.strip()
        return cleaned or None
    item = _as_mapping(content_item)
    if item is None:
        return None
    for key in ("text", "output_text", "value", "content"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        nested = _as_mapping(value)
        if nested:
            nested_value = nested.get("value")
            if isinstance(nested_value, str) and nested_value.strip():
                return nested_value.strip()
    return None


def _as_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _build_system_prompt(*, invoke_request: LlmInvokeRequest) -> str:
    return (
        f"{invoke_request.system_prompt.strip()}\n\n"
        "Return exactly one JSON object. Do not output markdown, code fences, or prose.\n"
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
