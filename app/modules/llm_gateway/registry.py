from __future__ import annotations

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
    if not model:
        model = (settings.app_llm_openai_model or "").strip()

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
        timeout_seconds=float(_runtime_defaults["timeout_seconds"]),
        max_retries=int(_runtime_defaults["max_retries"]),
        max_input_chars=int(_runtime_defaults["max_input_chars"]),
    )
