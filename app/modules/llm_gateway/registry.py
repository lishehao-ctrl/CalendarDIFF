from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from dotenv import dotenv_values
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

_runtime_defaults = {
    "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
    "max_retries": DEFAULT_MAX_RETRIES,
    "max_input_chars": DEFAULT_MAX_INPUT_CHARS,
}
_PROVIDER_FIELDS = (
    "FALLBACK_PROVIDER_IDS",
    "RESPONSES_BASE_URL",
    "CHAT_BASE_URL",
    "EXTRA_BODY_JSON",
    "MAX_INPUT_CHARS",
    "TIMEOUT_SECONDS",
    "MAX_RETRIES",
    "BASE_URL",
    "API_KEY",
    "PROTOCOL",
    "VENDOR",
    "MODEL",
)


@dataclass(frozen=True)
class LlmProviderDefinition:
    provider_id: str
    vendor: LlmVendorLiteral
    protocol: LlmProtocolLiteral
    model: str
    api_key: str
    base_url: str
    fallback_provider_ids: tuple[str, ...]
    timeout_seconds: float
    max_retries: int
    max_input_chars: int
    extra_body: dict
    chat_base_url: str | None = None
    responses_base_url: str | None = None


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
    settings = get_settings()
    provider_id = _clean_str(explicit_provider_id, settings.ingestion_llm_provider_id)
    if not provider_id:
        raise _config_error(
            code="parse_llm_upstream_error",
            message="INGESTION_LLM_PROVIDER_ID is not configured",
            provider_id=None,
            protocol=None,
        )
    provider = _resolve_named_provider_definition(provider_id=provider_id)
    protocol = explicit_protocol or provider.protocol
    provider = _override_provider_protocol(provider=provider, protocol=protocol)
    return _build_profile_from_definition(
        provider=provider,
        session_cache_enabled=bool(settings.ingestion_llm_session_cache_enabled),
    )


def resolve_agent_llm_profile(
    *,
    explicit_protocol: LlmProtocolLiteral | None = None,
    explicit_provider_id: str | None = None,
) -> ResolvedLlmProfile:
    settings = get_settings()
    provider_id = _clean_str(explicit_provider_id, settings.agent_llm_provider_id)
    if not provider_id:
        raise _config_error(
            code="parse_llm_upstream_error",
            message="AGENT_LLM_PROVIDER_ID is not configured",
            provider_id=None,
            protocol=None,
        )
    provider = _resolve_named_provider_definition(provider_id=provider_id)
    protocol = explicit_protocol or provider.protocol
    provider = _override_provider_protocol(provider=provider, protocol=protocol)
    return _build_profile_from_definition(
        provider=provider,
        session_cache_enabled=False,
    )


def resolve_llm_base_url(
    *,
    protocol: LlmProtocolLiteral,
    settings=None,
    fallback_base_url: str | None = None,
    provider_id: str | None = None,
) -> str:
    cleaned_provider_id = _clean_str(provider_id)
    if cleaned_provider_id:
        try:
            provider = _resolve_named_provider_definition(provider_id=cleaned_provider_id)
            return _resolve_provider_base_url(provider=provider, protocol=protocol)
        except LlmGatewayError:
            cleaned_fallback = (fallback_base_url or "").strip()
            if cleaned_fallback:
                return cleaned_fallback
            raise
    return (fallback_base_url or "").strip()


def resolve_agent_llm_base_url(
    *,
    protocol: LlmProtocolLiteral,
    settings=None,
    provider_id: str | None = None,
) -> str:
    cleaned_provider_id = _clean_str(provider_id)
    if cleaned_provider_id:
        try:
            provider = _resolve_named_provider_definition(provider_id=cleaned_provider_id)
            return _resolve_provider_base_url(provider=provider, protocol=protocol)
        except LlmGatewayError:
            cleaned_fallback = ""
            if cleaned_fallback:
                return cleaned_fallback
            raise
    return ""


def resolve_provider_fallback_ids(*, provider_id: str) -> tuple[str, ...]:
    cleaned_provider_id = _clean_str(provider_id)
    if not cleaned_provider_id:
        return ()
    try:
        provider = _resolve_named_provider_definition(provider_id=cleaned_provider_id)
    except LlmGatewayError:
        return ()
    return provider.fallback_provider_ids


def resolve_same_provider_fallback_protocols(*, profile: ResolvedLlmProfile) -> tuple[LlmProtocolLiteral, ...]:
    if profile.vendor not in {"openai", "dashscope_openai"}:
        return ()
    if profile.protocol == "responses":
        return ("chat_completions",)
    if profile.protocol == "chat_completions":
        return ("responses",)
    return ()


def _build_profile_from_definition(
    *,
    provider: LlmProviderDefinition,
    session_cache_enabled: bool,
) -> ResolvedLlmProfile:
    return ResolvedLlmProfile(
        provider_id=provider.provider_id,
        vendor=provider.vendor,
        protocol=provider.protocol,
        base_url=_resolve_provider_base_url(provider=provider, protocol=provider.protocol),
        model=provider.model,
        api_key=provider.api_key,
        session_cache_enabled=session_cache_enabled,
        timeout_seconds=provider.timeout_seconds,
        max_retries=provider.max_retries,
        max_input_chars=provider.max_input_chars,
        fallback_provider_ids=provider.fallback_provider_ids,
        extra_body=provider.extra_body,
    )


def _resolve_named_provider_definition(*, provider_id: str) -> LlmProviderDefinition:
    env = _merged_env()
    specs = _provider_specs(env)
    normalized_id = _normalize_provider_id(provider_id)
    spec = specs.get(normalized_id)
    if spec is None:
        raise _config_error(
            code="parse_llm_upstream_error",
            message=f"LLM provider '{provider_id}' is not configured",
            provider_id=normalized_id,
            protocol=None,
        )
    vendor = _parse_vendor(spec.get("VENDOR"), provider_id=normalized_id)
    protocol = _parse_protocol(spec.get("PROTOCOL"), provider_id=normalized_id)
    _validate_vendor_protocol(vendor=vendor, protocol=protocol, provider_id=normalized_id)
    model = _require_field(spec.get("MODEL"), provider_id=normalized_id, field_name="MODEL")
    api_key = _require_field(spec.get("API_KEY"), provider_id=normalized_id, field_name="API_KEY")
    base_url = _require_field(spec.get("BASE_URL"), provider_id=normalized_id, field_name="BASE_URL")
    fallback_provider_ids = tuple(
        _normalize_provider_id(value)
        for value in str(spec.get("FALLBACK_PROVIDER_IDS") or "").split(",")
        if str(value).strip()
    )
    _validate_named_provider_fallbacks(
        provider_id=normalized_id,
        vendor=vendor,
        fallback_provider_ids=fallback_provider_ids,
        specs=specs,
    )
    timeout_seconds = _parse_timeout(
        spec.get("TIMEOUT_SECONDS"),
        default=float(_runtime_defaults["timeout_seconds"]),
        provider_id=normalized_id,
    )
    max_retries = _parse_non_negative_int(
        spec.get("MAX_RETRIES"),
        default=int(_runtime_defaults["max_retries"]),
        provider_id=normalized_id,
        field_name="MAX_RETRIES",
    )
    max_input_chars = _parse_non_negative_int(
        spec.get("MAX_INPUT_CHARS"),
        default=int(_runtime_defaults["max_input_chars"]),
        provider_id=normalized_id,
        field_name="MAX_INPUT_CHARS",
    )
    extra_body = _parse_extra_body(
        spec.get("EXTRA_BODY_JSON"),
        provider_id=normalized_id,
        protocol=protocol,
        field_name="EXTRA_BODY_JSON",
    )
    chat_base_url = _clean_str(spec.get("CHAT_BASE_URL"))
    responses_base_url = _clean_str(spec.get("RESPONSES_BASE_URL"))
    return LlmProviderDefinition(
        provider_id=normalized_id,
        vendor=vendor,
        protocol=protocol,
        model=model,
        api_key=api_key,
        base_url=base_url,
        fallback_provider_ids=fallback_provider_ids,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        max_input_chars=max(max_input_chars, 256),
        extra_body=extra_body,
        chat_base_url=chat_base_url or None,
        responses_base_url=responses_base_url or None,
    )


def _validate_named_provider_fallbacks(
    *,
    provider_id: str,
    vendor: LlmVendorLiteral,
    fallback_provider_ids: tuple[str, ...],
    specs: dict[str, dict[str, str]],
) -> None:
    for fallback_provider_id in fallback_provider_ids:
        if fallback_provider_id == provider_id:
            raise _config_error(
                code="parse_llm_upstream_error",
                message=f"LLM provider '{provider_id}' cannot reference itself as a fallback provider",
                provider_id=provider_id,
                protocol=None,
            )
        fallback_spec = specs.get(fallback_provider_id)
        if fallback_spec is None:
            raise _config_error(
                code="parse_llm_upstream_error",
                message=f"LLM provider '{provider_id}' references unknown fallback provider '{fallback_provider_id}'",
                provider_id=provider_id,
                protocol=None,
            )
        fallback_vendor = _parse_vendor(fallback_spec.get("VENDOR"), provider_id=fallback_provider_id)
        if fallback_vendor != vendor:
            raise _config_error(
                code="parse_llm_upstream_error",
                message=(
                    f"LLM provider '{provider_id}' cannot use cross-vendor fallback provider "
                    f"'{fallback_provider_id}'"
                ),
                provider_id=provider_id,
                protocol=None,
            )


def _override_provider_protocol(
    *,
    provider: LlmProviderDefinition,
    protocol: LlmProtocolLiteral,
) -> LlmProviderDefinition:
    if protocol == provider.protocol:
        return provider
    _validate_vendor_protocol(vendor=provider.vendor, protocol=protocol, provider_id=provider.provider_id)
    return LlmProviderDefinition(
        provider_id=provider.provider_id,
        vendor=provider.vendor,
        protocol=protocol,
        model=provider.model,
        api_key=provider.api_key,
        base_url=provider.base_url,
        fallback_provider_ids=provider.fallback_provider_ids,
        timeout_seconds=provider.timeout_seconds,
        max_retries=provider.max_retries,
        max_input_chars=provider.max_input_chars,
        extra_body=provider.extra_body,
        chat_base_url=provider.chat_base_url,
        responses_base_url=provider.responses_base_url,
    )


def _resolve_provider_base_url(*, provider: LlmProviderDefinition, protocol: LlmProtocolLiteral) -> str:
    if protocol == "responses":
        return _clean_str(provider.responses_base_url, provider.base_url)
    if protocol == "chat_completions":
        return _clean_str(provider.chat_base_url, provider.base_url)
    return provider.base_url.strip()


def _provider_specs(env: dict[str, str]) -> dict[str, dict[str, str]]:
    specs: dict[str, dict[str, str]] = {}
    known_provider_ids: set[str] = set()
    for key in env:
        if not key.startswith("LLM_PROVIDER_") or not key.endswith("_VENDOR"):
            continue
        provider_id = _normalize_provider_id(key[len("LLM_PROVIDER_") : -len("_VENDOR")])
        if provider_id:
            known_provider_ids.add(provider_id)

    for key, value in env.items():
        if not key.startswith("LLM_PROVIDER_"):
            continue
        remainder = key[len("LLM_PROVIDER_") :]
        provider_id: str | None = None
        field_name: str | None = None
        for known_provider_id in sorted(known_provider_ids, key=len, reverse=True):
            prefix = f"{known_provider_id.upper()}_"
            if not remainder.startswith(prefix):
                continue
            candidate_field = remainder[len(prefix) :].strip().upper()
            if candidate_field in _PROVIDER_FIELDS:
                provider_id = known_provider_id
                field_name = candidate_field
                break
        if not provider_id or not field_name:
            for candidate in _PROVIDER_FIELDS:
                suffix = f"_{candidate}"
                if remainder.endswith(suffix):
                    provider_id = _normalize_provider_id(remainder[: -len(suffix)])
                    field_name = candidate
                    break
        if not provider_id or not field_name:
            continue
        specs.setdefault(provider_id, {})[field_name] = str(value).strip()
    return specs


def _merged_env() -> dict[str, str]:
    merged: dict[str, str] = {}
    env_file = Path(".env")
    if env_file.exists():
        for key, value in dotenv_values(env_file).items():
            if isinstance(key, str) and isinstance(value, str):
                merged[key] = value
    for key, value in os.environ.items():
        merged[key] = value
    return merged


def _parse_vendor(raw_value: str | None, *, provider_id: str) -> LlmVendorLiteral:
    value = _clean_str(raw_value).lower()
    if value in {"openai", "gemini", "dashscope_openai"}:
        return value  # type: ignore[return-value]
    raise _config_error(
        code="parse_llm_upstream_error",
        message=f"LLM provider '{provider_id}' has invalid vendor '{raw_value or ''}'",
        provider_id=provider_id,
        protocol=None,
    )


def _parse_protocol(raw_value: str | None, *, provider_id: str) -> LlmProtocolLiteral:
    value = _clean_str(raw_value).lower()
    if value in {"responses", "chat_completions", "gemini_generate_content"}:
        return value  # type: ignore[return-value]
    raise _config_error(
        code="parse_llm_upstream_error",
        message=f"LLM provider '{provider_id}' has invalid protocol '{raw_value or ''}'",
        provider_id=provider_id,
        protocol=None,
    )


def _validate_vendor_protocol(*, vendor: LlmVendorLiteral, protocol: LlmProtocolLiteral, provider_id: str) -> None:
    supported: dict[LlmVendorLiteral, set[LlmProtocolLiteral]] = {
        "openai": {"responses", "chat_completions"},
        "dashscope_openai": {"responses", "chat_completions"},
        "gemini": {"gemini_generate_content", "chat_completions"},
    }
    if protocol in supported[vendor]:
        return
    raise _config_error(
        code="parse_llm_upstream_error",
        message=f"LLM provider '{provider_id}' cannot use protocol '{protocol}' with vendor '{vendor}'",
        provider_id=provider_id,
        protocol=protocol,
    )


def _parse_extra_body(
    raw_value: str | None,
    *,
    provider_id: str,
    protocol: LlmProtocolLiteral,
    field_name: str,
) -> dict:
    cleaned = (raw_value or "").strip()
    if not cleaned:
        return {}
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise _config_error(
            code="parse_llm_upstream_error",
            message=f"{field_name} for '{provider_id}' is not valid json",
            provider_id=provider_id,
            protocol=protocol,
        ) from exc
    if not isinstance(parsed, dict):
        raise _config_error(
            code="parse_llm_upstream_error",
            message=f"{field_name} for '{provider_id}' must be a json object",
            provider_id=provider_id,
            protocol=protocol,
        )
    return parsed


def _normalize_timeout_seconds(raw_value: float | int | None) -> float:
    if raw_value is None:
        return float(_runtime_defaults["timeout_seconds"])
    parsed = float(raw_value)
    if parsed <= 0:
        return 0.0
    return max(parsed, 1.0)


def _parse_timeout(raw_value: str | None, *, default: float, provider_id: str) -> float:
    if raw_value is None or not str(raw_value).strip():
        return default
    try:
        return _normalize_timeout_seconds(float(raw_value))
    except Exception as exc:
        raise _config_error(
            code="parse_llm_upstream_error",
            message=f"LLM provider '{provider_id}' has invalid TIMEOUT_SECONDS",
            provider_id=provider_id,
            protocol=None,
        ) from exc


def _parse_non_negative_int(raw_value: str | None, *, default: int, provider_id: str, field_name: str) -> int:
    if raw_value is None or not str(raw_value).strip():
        return default
    try:
        return max(int(raw_value), 0)
    except Exception as exc:
        raise _config_error(
            code="parse_llm_upstream_error",
            message=f"LLM provider '{provider_id}' has invalid {field_name}",
            provider_id=provider_id,
            protocol=None,
        ) from exc


def _require_field(raw_value: str | None, *, provider_id: str, field_name: str) -> str:
    cleaned = _clean_str(raw_value)
    if cleaned:
        return cleaned
    raise _config_error(
        code="parse_llm_upstream_error",
        message=f"LLM provider '{provider_id}' is missing {field_name}",
        provider_id=provider_id,
        protocol=None,
    )


def _normalize_provider_id(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", value.strip().lower())


def _clean_str(*values: str | None) -> str:
    for value in values:
        cleaned = (value or "").strip()
        if cleaned:
            return cleaned
    return ""


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
