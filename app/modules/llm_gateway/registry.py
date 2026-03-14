from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.llm_gateway.contracts import LlmGatewayError, ResolvedLlmProfile

DEFAULT_PROVIDER_ID = "env-default"
DEFAULT_VENDOR = "openai-compatible"
DEFAULT_TIMEOUT_SECONDS = 12.0
DEFAULT_MAX_RETRIES = 1
DEFAULT_MAX_INPUT_CHARS = 12000
DEFAULT_API_MODE = "responses"

_runtime_defaults = {
    "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
    "max_retries": DEFAULT_MAX_RETRIES,
    "max_input_chars": DEFAULT_MAX_INPUT_CHARS,
}


def validate_ingestion_llm_config() -> ResolvedLlmProfile:
    # db/source_id are intentionally not used in env-only profile resolution.
    return resolve_llm_profile(None, source_id=None)


def set_llm_runtime_defaults(
    *,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
    max_input_chars: int | None = None,
) -> dict[str, float | int]:
    previous = dict(_runtime_defaults)

    if timeout_seconds is not None:
        _runtime_defaults["timeout_seconds"] = max(float(timeout_seconds), 1.0)
    if max_retries is not None:
        _runtime_defaults["max_retries"] = max(int(max_retries), 0)
    if max_input_chars is not None:
        _runtime_defaults["max_input_chars"] = max(int(max_input_chars), 256)

    return previous


@contextmanager
def llm_runtime_overrides(
    *,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
    max_input_chars: int | None = None,
) -> Iterator[None]:
    previous = set_llm_runtime_defaults(
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        max_input_chars=max_input_chars,
    )
    try:
        yield
    finally:
        set_llm_runtime_defaults(
            timeout_seconds=float(previous["timeout_seconds"]),
            max_retries=int(previous["max_retries"]),
            max_input_chars=int(previous["max_input_chars"]),
        )


def resolve_llm_profile(
    db: Session | None,
    *,
    source_id: int | None,
    explicit_provider_id: str | None = None,
) -> ResolvedLlmProfile:
    del db
    del source_id
    del explicit_provider_id

    settings = get_settings()
    base_url = (settings.ingestion_llm_base_url or "").strip()
    api_key = (settings.ingestion_llm_api_key or "").strip()
    model = (settings.ingestion_llm_model or "").strip()
    api_mode = (settings.ingestion_llm_api_mode or "").strip().lower() or DEFAULT_API_MODE
    extra_body = _parse_extra_body(settings.ingestion_llm_extra_body_json)
    timeout_seconds = (
        max(float(settings.ingestion_llm_timeout_seconds), 1.0)
        if settings.ingestion_llm_timeout_seconds is not None
        else float(_runtime_defaults["timeout_seconds"])
    )
    max_retries = (
        max(int(settings.ingestion_llm_max_retries), 0)
        if settings.ingestion_llm_max_retries is not None
        else int(_runtime_defaults["max_retries"])
    )
    max_input_chars = (
        max(int(settings.ingestion_llm_max_input_chars), 256)
        if settings.ingestion_llm_max_input_chars is not None
        else int(_runtime_defaults["max_input_chars"])
    )
    if not model:
        model = (settings.app_llm_openai_model or "").strip()

    if api_mode not in {"chat_completions", "responses"}:
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message=f"INGESTION_LLM_API_MODE is invalid: {api_mode}",
            retryable=False,
            provider_id=DEFAULT_PROVIDER_ID,
            api_mode=DEFAULT_API_MODE,
        )

    if not base_url:
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message="INGESTION_LLM_BASE_URL is not configured",
            retryable=False,
            provider_id=DEFAULT_PROVIDER_ID,
            api_mode=api_mode,
        )
    if not api_key:
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message="INGESTION_LLM_API_KEY is not configured",
            retryable=False,
            provider_id=DEFAULT_PROVIDER_ID,
            api_mode=api_mode,
        )
    if not model:
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message="INGESTION_LLM_MODEL is not configured",
            retryable=False,
            provider_id=DEFAULT_PROVIDER_ID,
            api_mode=api_mode,
        )

    return ResolvedLlmProfile(
        provider_id=DEFAULT_PROVIDER_ID,
        vendor=DEFAULT_VENDOR,
        base_url=base_url,
        api_mode=api_mode,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        max_input_chars=max_input_chars,
        extra_body=extra_body,
    )


def _parse_extra_body(raw_value: str | None) -> dict:
    cleaned = (raw_value or "").strip()
    if not cleaned:
        return {}
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message="INGESTION_LLM_EXTRA_BODY_JSON is not valid json",
            retryable=False,
            provider_id=DEFAULT_PROVIDER_ID,
            api_mode=DEFAULT_API_MODE,
        ) from exc
    if not isinstance(parsed, dict):
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message="INGESTION_LLM_EXTRA_BODY_JSON must be a json object",
            retryable=False,
            provider_id=DEFAULT_PROVIDER_ID,
            api_mode=DEFAULT_API_MODE,
        )
    return parsed
