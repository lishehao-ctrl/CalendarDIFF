from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.llm_gateway.contracts import LlmGatewayError, ResolvedLlmProfile

DEFAULT_PROVIDER_ID = "env-default"
DEFAULT_VENDOR = "openai-compatible"
DEFAULT_TIMEOUT_SECONDS = 12.0
DEFAULT_MAX_RETRIES = 1
DEFAULT_MAX_INPUT_CHARS = 12000


def clear_llm_registry_cache() -> None:
    # Kept for compatibility with existing imports.
    return


def resolve_llm_profile(
    db: Session,
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

    if not base_url:
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message="INGESTION_LLM_BASE_URL is not configured",
            retryable=False,
            provider_id=DEFAULT_PROVIDER_ID,
            api_mode="chat_completions",
        )
    if not api_key:
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message="INGESTION_LLM_API_KEY is not configured",
            retryable=False,
            provider_id=DEFAULT_PROVIDER_ID,
            api_mode="chat_completions",
        )
    if not model:
        raise LlmGatewayError(
            code="parse_llm_upstream_error",
            message="INGESTION_LLM_MODEL is not configured",
            retryable=False,
            provider_id=DEFAULT_PROVIDER_ID,
            api_mode="chat_completions",
        )

    return ResolvedLlmProfile(
        provider_id=DEFAULT_PROVIDER_ID,
        vendor=DEFAULT_VENDOR,
        base_url=base_url,
        api_mode="chat_completions",
        model=model,
        api_key=api_key,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        max_retries=DEFAULT_MAX_RETRIES,
        max_input_chars=DEFAULT_MAX_INPUT_CHARS,
    )
