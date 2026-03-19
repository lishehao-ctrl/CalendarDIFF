from __future__ import annotations

from typing import Any


def int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


def normalize_llm_usage(raw_usage: dict[str, Any] | None) -> dict[str, int | None]:
    if not isinstance(raw_usage, dict):
        return {
            "input_tokens": None,
            "cached_input_tokens": None,
            "cache_creation_input_tokens": None,
            "output_tokens": None,
            "reasoning_tokens": None,
            "total_tokens": None,
        }

    input_tokens = int_or_none(raw_usage.get("input_tokens"))
    output_tokens = int_or_none(raw_usage.get("output_tokens"))
    total_tokens = int_or_none(raw_usage.get("total_tokens"))
    cached_input_tokens = None
    cache_creation_input_tokens = None
    reasoning_tokens = None

    input_details = raw_usage.get("input_tokens_details") if isinstance(raw_usage.get("input_tokens_details"), dict) else {}
    output_details = raw_usage.get("output_tokens_details") if isinstance(raw_usage.get("output_tokens_details"), dict) else {}
    prompt_details = raw_usage.get("prompt_tokens_details") if isinstance(raw_usage.get("prompt_tokens_details"), dict) else {}

    cached_input_tokens = int_or_none(input_details.get("cached_tokens"))
    if cached_input_tokens is None:
        cached_input_tokens = int_or_none(prompt_details.get("cached_tokens"))

    cache_creation_input_tokens = int_or_none(prompt_details.get("cache_creation_input_tokens"))
    if cache_creation_input_tokens is None:
        cache_creation = prompt_details.get("cache_creation")
        if isinstance(cache_creation, dict):
            cache_creation_input_tokens = int_or_none(cache_creation.get("ephemeral_5m_input_tokens"))

    reasoning_tokens = int_or_none(output_details.get("reasoning_tokens"))

    x_details = raw_usage.get("x_details")
    if isinstance(x_details, list):
        for item in x_details:
            if not isinstance(item, dict):
                continue
            if input_tokens is None:
                input_tokens = int_or_none(item.get("input_tokens"))
            if output_tokens is None:
                output_tokens = int_or_none(item.get("output_tokens"))
            if total_tokens is None:
                total_tokens = int_or_none(item.get("total_tokens"))
            nested_output_details = item.get("output_tokens_details")
            if isinstance(nested_output_details, dict) and reasoning_tokens is None:
                reasoning_tokens = int_or_none(nested_output_details.get("reasoning_tokens"))
            nested_prompt_details = item.get("prompt_tokens_details")
            if isinstance(nested_prompt_details, dict):
                if cached_input_tokens is None:
                    cached_input_tokens = int_or_none(nested_prompt_details.get("cached_tokens"))
                if cache_creation_input_tokens is None:
                    cache_creation_input_tokens = int_or_none(nested_prompt_details.get("cache_creation_input_tokens"))
                if cache_creation_input_tokens is None:
                    nested_creation = nested_prompt_details.get("cache_creation")
                    if isinstance(nested_creation, dict):
                        cache_creation_input_tokens = int_or_none(nested_creation.get("ephemeral_5m_input_tokens"))

    if input_tokens is None:
        input_tokens = int_or_none(raw_usage.get("prompt_tokens"))
    if output_tokens is None:
        output_tokens = int_or_none(raw_usage.get("completion_tokens"))

    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_creation_input_tokens": cache_creation_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
    }


__all__ = ["int_or_none", "normalize_llm_usage"]
