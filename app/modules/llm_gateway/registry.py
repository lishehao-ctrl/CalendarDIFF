from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Iterator
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.llm_gateway.contracts import (
    LlmGatewayError,
    LlmProtocolLiteral,
    LlmVendorLiteral,
    ResolvedLlmProfile,
)

DEFAULT_TIMEOUT_SECONDS = 12.0
DEFAULT_MAX_RETRIES = 1
DEFAULT_MAX_INPUT_CHARS = 12000
DEFAULT_PROVIDER_ID = "env-default"

_runtime_defaults = {
    "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
    "max_retries": DEFAULT_MAX_RETRIES,
    "max_input_chars": DEFAULT_MAX_INPUT_CHARS,
}


def validate_ingestion_llm_config() -> ResolvedLlmProfile:
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
    explicit_protocol: LlmProtocolLiteral | None = None,
) -> ResolvedLlmProfile:
    del db
    del source_id
    del explicit_provider_id
    settings = get_settings()
    return _build_profile(
        protocol=explicit_protocol or "responses",
        session_cache_enabled=bool(settings.ingestion_llm_session_cache_enabled),
    )


def resolve_agent_llm_profile(
    *,
    explicit_protocol: LlmProtocolLiteral | None = None,
    explicit_provider_id: str | None = None,
) -> ResolvedLlmProfile:
    del explicit_provider_id
    return _build_profile(
        protocol=explicit_protocol or "responses",
        session_cache_enabled=False,
    )


def resolve_llm_base_url(
    *,
    protocol: LlmProtocolLiteral,
    settings=None,
    fallback_base_url: str | None = None,
    provider_id: str | None = None,
) -> str:
    del provider_id
    current_settings = settings or get_settings()
    return _resolve_protocol_base_url(
        protocol=protocol,
        base_url=current_settings.llm_base_url,
        responses_base_url=current_settings.llm_responses_base_url,
        fallback_base_url=fallback_base_url,
    )


def resolve_agent_llm_base_url(
    *,
    protocol: LlmProtocolLiteral,
    settings=None,
    provider_id: str | None = None,
) -> str:
    del provider_id
    return resolve_llm_base_url(protocol=protocol, settings=settings)


def _build_profile(
    *,
    protocol: LlmProtocolLiteral,
    session_cache_enabled: bool,
) -> ResolvedLlmProfile:
    settings = get_settings()
    base_url = _require_canonical_setting(settings.llm_base_url, "LLM_BASE_URL")
    protocol_base_url = _resolve_protocol_base_url(
        protocol=protocol,
        base_url=base_url,
        responses_base_url=settings.llm_responses_base_url,
        fallback_base_url=None,
    )
    api_key = _require_canonical_setting(settings.llm_api_key, "LLM_API_KEY")
    model = _require_canonical_setting(settings.llm_model, "LLM_MODEL")
    _validate_protocol(protocol=protocol, base_url=base_url)
    vendor = _infer_vendor_from_base_url(base_url)
    return ResolvedLlmProfile(
        provider_id=DEFAULT_PROVIDER_ID,
        vendor=vendor,
        protocol=protocol,
        base_url=protocol_base_url,
        model=model,
        api_key=api_key,
        session_cache_enabled=session_cache_enabled,
        timeout_seconds=_resolve_timeout_seconds(settings),
        max_retries=_resolve_max_retries(settings),
        max_input_chars=_resolve_max_input_chars(settings),
        extra_body=_resolve_extra_body(settings),
        fallback_provider_ids=(),
    )


def _resolve_timeout_seconds(settings) -> float:
    raw_value = settings.llm_timeout_seconds
    if raw_value is None:
        return float(_runtime_defaults["timeout_seconds"])
    parsed = float(raw_value)
    if parsed <= 0:
        return 0.0
    return max(parsed, 1.0)


def _resolve_max_retries(settings) -> int:
    raw_value = settings.llm_max_retries
    if raw_value is None:
        return int(_runtime_defaults["max_retries"])
    return max(int(raw_value), 0)


def _resolve_max_input_chars(settings) -> int:
    raw_value = settings.llm_max_input_chars
    if raw_value is None:
        return int(_runtime_defaults["max_input_chars"])
    return max(int(raw_value), 256)


def _resolve_extra_body(settings) -> dict:
    cleaned = _clean_str(settings.llm_extra_body_json)
    if not cleaned:
        base_url = _clean_str(settings.llm_base_url)
        if _infer_vendor_from_base_url(base_url) == "dashscope_openai":
            return {"enable_thinking": False}
        return {}
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise _config_error(
            code="parse_llm_upstream_error",
            message="LLM_EXTRA_BODY_JSON must be valid json",
            provider_id=DEFAULT_PROVIDER_ID,
            protocol=None,
        ) from exc
    if not isinstance(parsed, dict):
        raise _config_error(
            code="parse_llm_upstream_error",
            message="LLM_EXTRA_BODY_JSON must be a json object",
            provider_id=DEFAULT_PROVIDER_ID,
            protocol=None,
        )
    return parsed


def _infer_vendor_from_base_url(base_url: str) -> LlmVendorLiteral:
    hostname = (urlparse(base_url).hostname or "").lower()
    if "dashscope" in hostname:
        return "dashscope_openai"
    return "openai"


def _validate_protocol(*, protocol: LlmProtocolLiteral, base_url: str) -> None:
    if protocol in {"responses", "chat_completions"}:
        return
    raise _config_error(
        code="parse_llm_upstream_error",
        message=(
            f"LLM protocol '{protocol}' is not supported by the canonical env-default "
            f"openai-compatible profile for base url '{base_url}'"
        ),
        provider_id=DEFAULT_PROVIDER_ID,
        protocol=protocol,
    )


def _require_canonical_setting(raw_value: str | None, env_name: str) -> str:
    cleaned = _clean_str(raw_value)
    if cleaned:
        return cleaned
    raise _config_error(
        code="parse_llm_upstream_error",
        message=f"{env_name} is not configured",
        provider_id=DEFAULT_PROVIDER_ID,
        protocol=None,
    )


def _clean_str(*values: str | None) -> str:
    for value in values:
        cleaned = (value or "").strip()
        if cleaned:
            return cleaned
    return ""


def _resolve_protocol_base_url(
    *,
    protocol: LlmProtocolLiteral,
    base_url: str | None,
    responses_base_url: str | None,
    fallback_base_url: str | None,
) -> str:
    if protocol == "responses":
        return _clean_str(fallback_base_url, responses_base_url, base_url)
    return _clean_str(fallback_base_url, base_url)


def _config_error(
    *,
    code: str,
    message: str,
    provider_id: str | None,
    protocol: LlmProtocolLiteral | None,
) -> LlmGatewayError:
    return LlmGatewayError(
        code=code,
        message=message,
        retryable=False,
        provider_id=provider_id,
        protocol=protocol,
    )
