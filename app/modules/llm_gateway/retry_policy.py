from __future__ import annotations

LLM_FORMAT_MAX_ATTEMPTS = 4  # initial call + 3 retries

FORMAT_RETRY_CODES = {
    "parse_llm_schema_invalid",
    "parse_llm_empty_output",
}


def is_format_retryable_code(code: str | None) -> bool:
    if not isinstance(code, str):
        return False
    return code in FORMAT_RETRY_CODES
