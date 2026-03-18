from __future__ import annotations

from app.core.config import get_settings
from app.modules.llm_gateway.registry import resolve_llm_profile
from app.modules.llm_gateway.transport_openai_compat import build_openai_compat_endpoint


def test_resolve_llm_profile_falls_back_to_app_openai_model(monkeypatch) -> None:
    monkeypatch.setenv("INGESTION_LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("INGESTION_LLM_API_KEY", "test-key")
    monkeypatch.setenv("INGESTION_LLM_MODEL", "")
    monkeypatch.setenv("APP_LLM_OPENAI_MODEL", "fallback-model")
    monkeypatch.setenv("INGESTION_LLM_EXTRA_BODY_JSON", '{"enable_thinking":true}')
    monkeypatch.setenv("INGESTION_LLM_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("INGESTION_LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("INGESTION_LLM_MAX_INPUT_CHARS", "9000")
    get_settings.cache_clear()
    try:
        profile = resolve_llm_profile(None, source_id=None)
        assert profile.model == "fallback-model"
        assert profile.api_mode == "chat_completions"
        assert profile.extra_body == {"enable_thinking": True}
        assert profile.timeout_seconds == 30.0
        assert profile.max_retries == 2
        assert profile.max_input_chars == 9000
    finally:
        get_settings.cache_clear()


def test_build_openai_compat_endpoint_uses_responses_path() -> None:
    assert (
        build_openai_compat_endpoint(
            base_url="https://dashscope-us.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1",
            api_mode="responses",
        )
        == "https://dashscope-us.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1/responses"
    )


def test_resolve_llm_profile_allows_zero_timeout_to_disable_transport_timeout(monkeypatch) -> None:
    monkeypatch.setenv("INGESTION_LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("INGESTION_LLM_API_KEY", "test-key")
    monkeypatch.setenv("INGESTION_LLM_MODEL", "test-model")
    monkeypatch.setenv("INGESTION_LLM_TIMEOUT_SECONDS", "0")
    get_settings.cache_clear()
    try:
        profile = resolve_llm_profile(None, source_id=None)
        assert profile.timeout_seconds == 0.0
    finally:
        get_settings.cache_clear()


def test_resolve_llm_profile_reads_session_cache_flag(monkeypatch) -> None:
    monkeypatch.setenv("INGESTION_LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("INGESTION_LLM_API_KEY", "test-key")
    monkeypatch.setenv("INGESTION_LLM_MODEL", "test-model")
    monkeypatch.setenv("INGESTION_LLM_SESSION_CACHE_ENABLED", "true")
    get_settings.cache_clear()
    try:
        profile = resolve_llm_profile(None, source_id=None)
        assert profile.session_cache_enabled is True
    finally:
        get_settings.cache_clear()
    assert (
        build_openai_compat_endpoint(
            base_url="https://dashscope-us.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1/chat/completions",
            api_mode="responses",
        )
        == "https://dashscope-us.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1/responses"
    )
