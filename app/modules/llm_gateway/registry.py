from __future__ import annotations

import os
import time

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.db.models import LlmApiMode, LlmProvider, SourceLlmBinding
from app.modules.llm_gateway.contracts import LlmApiModeLiteral, LlmGatewayError, ResolvedLlmProfile

_PROFILE_CACHE: dict[str, tuple[float, ResolvedLlmProfile]] = {}


def clear_llm_registry_cache() -> None:
    _PROFILE_CACHE.clear()


def resolve_llm_profile(
    db: Session,
    *,
    source_id: int | None,
    explicit_provider_id: str | None = None,
) -> ResolvedLlmProfile:
    settings = get_settings()
    cache_ttl = max(int(settings.llm_registry_cache_ttl_seconds), 0)
    cache_key = _build_cache_key(source_id=source_id, explicit_provider_id=explicit_provider_id)
    now = time.time()
    if cache_ttl > 0:
        cached = _PROFILE_CACHE.get(cache_key)
        if cached is not None and now - cached[0] <= cache_ttl:
            return cached[1]

    provider, binding = _resolve_provider_and_binding(
        db,
        source_id=source_id,
        explicit_provider_id=explicit_provider_id,
    )
    profile = _materialize_profile(
        provider=provider,
        binding=binding,
        allow_http_base_url=settings.llm_allow_http_base_url,
    )
    if cache_ttl > 0:
        _PROFILE_CACHE[cache_key] = (now, profile)
    return profile


def _resolve_provider_and_binding(
    db: Session,
    *,
    source_id: int | None,
    explicit_provider_id: str | None,
) -> tuple[LlmProvider, SourceLlmBinding | None]:
    if explicit_provider_id:
        provider = db.scalar(
            select(LlmProvider).where(
                LlmProvider.provider_id == explicit_provider_id.strip(),
            )
        )
        if provider is None:
            raise LlmGatewayError(
                code="parse_llm_provider_not_found",
                message=f"llm provider not found: {explicit_provider_id}",
                retryable=False,
                provider_id=explicit_provider_id.strip(),
                api_mode=None,
            )
        if not provider.enabled:
            raise LlmGatewayError(
                code="parse_llm_provider_disabled",
                message=f"llm provider is disabled: {provider.provider_id}",
                retryable=False,
                provider_id=provider.provider_id,
                api_mode=None,
            )
        return provider, None

    if source_id is not None:
        binding = db.scalar(
            select(SourceLlmBinding)
            .options(joinedload(SourceLlmBinding.provider))
            .where(SourceLlmBinding.source_id == source_id)
        )
        if binding is not None and binding.enabled:
            provider = binding.provider
            if provider is None:
                raise LlmGatewayError(
                    code="parse_llm_provider_not_found",
                    message=f"llm provider missing for source binding: source_id={source_id}",
                    retryable=False,
                    provider_id=None,
                    api_mode=None,
                )
            if not provider.enabled:
                raise LlmGatewayError(
                    code="parse_llm_provider_disabled",
                    message=f"source binding points to disabled llm provider: {provider.provider_id}",
                    retryable=False,
                    provider_id=provider.provider_id,
                    api_mode=None,
                )
            return provider, binding

    provider = db.scalar(
        select(LlmProvider)
        .where(
            LlmProvider.enabled.is_(True),
            LlmProvider.is_default.is_(True),
        )
        .order_by(LlmProvider.updated_at.desc(), LlmProvider.id.asc())
        .limit(1)
    )
    if provider is None:
        provider = db.scalar(
            select(LlmProvider)
            .where(LlmProvider.enabled.is_(True))
            .order_by(LlmProvider.updated_at.desc(), LlmProvider.id.asc())
            .limit(1)
        )
    if provider is None:
        raise LlmGatewayError(
            code="parse_llm_provider_not_found",
            message="no enabled llm provider configured",
            retryable=False,
            provider_id=None,
            api_mode=None,
        )
    return provider, None


def _materialize_profile(
    *,
    provider: LlmProvider,
    binding: SourceLlmBinding | None,
    allow_http_base_url: bool,
) -> ResolvedLlmProfile:
    provider_id = provider.provider_id.strip()
    if not provider_id:
        raise LlmGatewayError(
            code="parse_llm_provider_not_found",
            message="llm provider_id is blank",
            retryable=False,
            provider_id=None,
            api_mode=None,
        )

    model = provider.model.strip()
    if binding is not None and binding.model_override and binding.model_override.strip():
        model = binding.model_override.strip()
    if not model:
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message=f"llm provider model is blank: {provider_id}",
            retryable=False,
            provider_id=provider_id,
            api_mode=None,
        )

    api_mode = provider.api_mode
    if binding is not None and binding.api_mode_override is not None:
        api_mode = binding.api_mode_override
    api_mode_value = _normalize_api_mode(api_mode=api_mode, provider_id=provider_id)

    base_url = provider.base_url.strip()
    if not base_url:
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message=f"llm provider base_url is blank: {provider_id}",
            retryable=False,
            provider_id=provider_id,
            api_mode=api_mode_value,
        )
    if base_url.startswith("http://") and not allow_http_base_url:
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message=f"http base_url is blocked for llm provider: {provider_id}",
            retryable=False,
            provider_id=provider_id,
            api_mode=api_mode_value,
        )

    key_ref = provider.api_key_ref.strip()
    api_key = os.getenv(key_ref) if key_ref else None
    if not api_key:
        raise LlmGatewayError(
            code="parse_llm_provider_key_missing",
            message=f"llm provider api_key_ref env missing: {key_ref or '<blank>'}",
            retryable=False,
            provider_id=provider_id,
            api_mode=api_mode_value,
        )

    return ResolvedLlmProfile(
        provider_id=provider_id,
        vendor=provider.vendor.strip() or "unknown",
        base_url=base_url,
        api_mode=api_mode_value,
        model=model,
        api_key=api_key,
        timeout_seconds=max(float(provider.timeout_seconds or 0), 1.0),
        max_retries=max(int(provider.max_retries or 0), 0),
        max_input_chars=max(int(provider.max_input_chars or 0), 0),
    )


def _normalize_api_mode(*, api_mode: LlmApiMode, provider_id: str) -> LlmApiModeLiteral:
    if api_mode == LlmApiMode.CHAT_COMPLETIONS:
        return "chat_completions"
    if api_mode == LlmApiMode.RESPONSES:
        return "responses"
    raise LlmGatewayError(
        code="parse_llm_mode_unsupported",
        message=f"unsupported llm api_mode for provider: {provider_id}",
        retryable=False,
        provider_id=provider_id,
        api_mode=None,
    )


def _build_cache_key(*, source_id: int | None, explicit_provider_id: str | None) -> str:
    return f"source={source_id or 0}|provider={explicit_provider_id or ''}"
