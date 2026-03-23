from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.llm_gateway.contracts import LlmApiModeLiteral, LlmGatewayError, ResolvedLlmProfile

DEFAULT_PROVIDER_ID = "env-default"
DEFAULT_VENDOR = "openai-compatible"
DEFAULT_TIMEOUT_SECONDS = 12.0
DEFAULT_MAX_RETRIES = 1
DEFAULT_MAX_INPUT_CHARS = 12000
DEFAULT_API_MODE = "responses"
DEFAULT_AGENT_API_MODE = "chat_completions"

_runtime_defaults = {
    "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
    "max_retries": DEFAULT_MAX_RETRIES,
    "max_input_chars": DEFAULT_MAX_INPUT_CHARS,
}


def validate_ingestion_llm_config() -> ResolvedLlmProfile:
    # db/source_id are intentionally not used in env-only profile resolution.
    return resolve_llm_profile(None, source_id=None)


def validate_agent_llm_config() -> ResolvedLlmProfile:
    return resolve_agent_llm_profile()


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
    explicit_api_mode: LlmApiModeLiteral | None = None,
) -> ResolvedLlmProfile:
    del db
    del source_id
    del explicit_provider_id

    settings = get_settings()
    api_key = (settings.ingestion_llm_api_key or "").strip()
    model = (settings.ingestion_llm_model or "").strip()
    api_mode = explicit_api_mode or (settings.ingestion_llm_api_mode or "").strip().lower() or DEFAULT_API_MODE
    base_url = resolve_llm_base_url(api_mode=api_mode, settings=settings)
    extra_body = _parse_extra_body(settings.ingestion_llm_extra_body_json)
    timeout_seconds = (
        _normalize_timeout_seconds(settings.ingestion_llm_timeout_seconds)
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
        session_cache_enabled=bool(settings.ingestion_llm_session_cache_enabled),
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        max_input_chars=max_input_chars,
        extra_body=extra_body,
    )


def resolve_agent_llm_profile() -> ResolvedLlmProfile:
    settings = get_settings()
    api_key = _coalesce_str(settings.agent_llm_api_key, settings.ingestion_llm_api_key)
    model = _coalesce_str(settings.agent_llm_model, settings.ingestion_llm_model, settings.app_llm_openai_model)
    api_mode = (_coalesce_str(settings.agent_llm_api_mode) or DEFAULT_AGENT_API_MODE).lower()
    base_url = resolve_agent_llm_base_url(api_mode=api_mode, settings=settings)
    extra_body = _parse_extra_body(settings.agent_llm_extra_body_json or settings.ingestion_llm_extra_body_json)
    timeout_seconds = (
        _normalize_timeout_seconds(settings.agent_llm_timeout_seconds)
        if settings.agent_llm_timeout_seconds is not None
        else (
            _normalize_timeout_seconds(settings.ingestion_llm_timeout_seconds)
            if settings.ingestion_llm_timeout_seconds is not None
            else float(_runtime_defaults["timeout_seconds"])
        )
    )
    max_retries = (
        max(int(settings.agent_llm_max_retries), 0)
        if settings.agent_llm_max_retries is not None
        else (
            max(int(settings.ingestion_llm_max_retries), 0)
            if settings.ingestion_llm_max_retries is not None
            else int(_runtime_defaults["max_retries"])
        )
    )
    max_input_chars = (
        max(int(settings.agent_llm_max_input_chars), 256)
        if settings.agent_llm_max_input_chars is not None
        else (
            max(int(settings.ingestion_llm_max_input_chars), 256)
            if settings.ingestion_llm_max_input_chars is not None
            else int(_runtime_defaults["max_input_chars"])
        )
    )

    if api_mode not in {"chat_completions", "responses"}:
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message=f"AGENT_LLM_API_MODE is invalid: {api_mode}",
            retryable=False,
            provider_id="agent-env-default",
            api_mode=DEFAULT_AGENT_API_MODE,
        )
    if not base_url:
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message="AGENT_LLM_BASE_URL is not configured",
            retryable=False,
            provider_id="agent-env-default",
            api_mode=api_mode,
        )
    if not api_key:
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message="AGENT_LLM_API_KEY is not configured",
            retryable=False,
            provider_id="agent-env-default",
            api_mode=api_mode,
        )
    if not model:
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message="AGENT_LLM_MODEL is not configured",
            retryable=False,
            provider_id="agent-env-default",
            api_mode=api_mode,
        )

    return ResolvedLlmProfile(
        provider_id="agent-env-default",
        vendor=DEFAULT_VENDOR,
        base_url=base_url,
        api_mode=api_mode,
        model=model,
        api_key=api_key,
        session_cache_enabled=False,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        max_input_chars=max_input_chars,
        extra_body=extra_body,
    )


def resolve_llm_base_url(
    *,
    api_mode: LlmApiModeLiteral,
    settings=None,
    fallback_base_url: str | None = None,
) -> str:
    current_settings = settings or get_settings()
    if api_mode == "responses":
        mode_specific_base_url = current_settings.ingestion_llm_responses_base_url
    else:
        mode_specific_base_url = current_settings.ingestion_llm_chat_base_url

    for candidate in (mode_specific_base_url, fallback_base_url, current_settings.ingestion_llm_base_url):
        cleaned = (candidate or "").strip()
        if cleaned:
            return cleaned
    return ""


def resolve_agent_llm_base_url(
    *,
    api_mode: LlmApiModeLiteral,
    settings=None,
) -> str:
    current_settings = settings or get_settings()
    if api_mode == "responses":
        mode_specific_base_url = current_settings.agent_llm_responses_base_url
    else:
        mode_specific_base_url = current_settings.agent_llm_chat_base_url

    for candidate in (
        mode_specific_base_url,
        current_settings.agent_llm_base_url,
        resolve_llm_base_url(api_mode=api_mode, settings=current_settings),
    ):
        cleaned = (candidate or "").strip()
        if cleaned:
            return cleaned
    return ""


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


def _normalize_timeout_seconds(raw_value: float | int | None) -> float:
    if raw_value is None:
        return float(_runtime_defaults["timeout_seconds"])
    parsed = float(raw_value)
    if parsed <= 0:
        return 0.0
    return max(parsed, 1.0)


def _coalesce_str(*values: str | None) -> str:
    for value in values:
        cleaned = (value or "").strip()
        if cleaned:
            return cleaned
    return ""
