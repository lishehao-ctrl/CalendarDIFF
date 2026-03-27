from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.modules.llm_gateway.contracts import LlmInvokeRequest
from app.modules.llm_gateway.registry import (
    resolve_agent_llm_base_url,
    resolve_agent_llm_profile,
    resolve_judge_llm_profile,
    resolve_llm_base_url,
    resolve_llm_profile,
)
from app.modules.llm_gateway.route_registry import resolve_llm_routes
from app.modules.llm_gateway.transport_openai_compat import build_openai_compat_endpoint


def test_env_default_ingestion_profile_reads_canonical_llm_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_RESPONSES_BASE_URL", "")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "gpt-5-mini")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("LLM_MAX_INPUT_CHARS", "9000")
    monkeypatch.setenv("LLM_EXTRA_BODY_JSON", '{"reasoning":{"effort":"low"}}')
    get_settings.cache_clear()
    try:
        profile = resolve_llm_profile(None, source_id=None)
        assert profile.provider_id == "env-default"
        assert profile.vendor == "openai"
        assert profile.protocol == "responses"
        assert profile.model == "gpt-5-mini"
        assert profile.api_key == "test-key"
        assert profile.base_url == "https://api.openai.com/v1"
        assert profile.timeout_seconds == 30.0
        assert profile.max_retries == 2
        assert profile.max_input_chars == 9000
        assert profile.extra_body == {"reasoning": {"effort": "low"}}
    finally:
        get_settings.cache_clear()


def test_dashscope_base_url_inferrs_openai_compat_vendor(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://dashscope-us.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "qwen3.5-flash")
    monkeypatch.delenv("LLM_EXTRA_BODY_JSON", raising=False)
    get_settings.cache_clear()
    try:
        profile = resolve_agent_llm_profile(explicit_protocol="chat_completions")
        assert profile.provider_id == "env-default"
        assert profile.vendor == "dashscope_openai"
        assert profile.protocol == "chat_completions"
        assert profile.base_url == "https://dashscope-us.aliyuncs.com/compatible-mode/v1"
        assert profile.session_cache_enabled is False
        assert profile.extra_body == {"enable_thinking": False}
    finally:
        get_settings.cache_clear()


def test_ingestion_profile_defaults_session_cache_enabled(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "gpt-5-mini")
    monkeypatch.delenv("INGESTION_LLM_SESSION_CACHE_ENABLED", raising=False)
    get_settings.cache_clear()
    try:
        profile = resolve_llm_profile(None, source_id=None)
        assert profile.session_cache_enabled is True
    finally:
        get_settings.cache_clear()


def test_resolve_base_url_reuses_single_canonical_base_url(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://example.com/root/v1")
    monkeypatch.setenv("LLM_RESPONSES_BASE_URL", "")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    get_settings.cache_clear()
    try:
        assert resolve_llm_base_url(protocol="responses") == "https://example.com/root/v1"
        assert resolve_agent_llm_base_url(protocol="chat_completions") == "https://example.com/root/v1"
        assert build_openai_compat_endpoint(base_url=resolve_llm_base_url(protocol="responses"), protocol="responses") == "https://example.com/root/v1/responses"
        assert build_openai_compat_endpoint(base_url=resolve_llm_base_url(protocol="chat_completions"), protocol="chat_completions") == "https://example.com/root/v1/chat/completions"
    finally:
        get_settings.cache_clear()


def test_responses_protocol_can_use_dedicated_responses_base_url(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://dashscope-us.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("LLM_RESPONSES_BASE_URL", "https://dashscope-us.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "qwen3.5-flash")
    get_settings.cache_clear()
    try:
        responses_profile = resolve_llm_profile(None, source_id=None)
        chat_profile = resolve_agent_llm_profile(explicit_protocol="chat_completions")
        assert responses_profile.base_url == "https://dashscope-us.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1"
        assert chat_profile.base_url == "https://dashscope-us.aliyuncs.com/compatible-mode/v1"
    finally:
        get_settings.cache_clear()


def test_resolve_llm_routes_returns_single_primary_route(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "gpt-5-mini")
    get_settings.cache_clear()
    try:
        routes = resolve_llm_routes(
            None,
            invoke_request=LlmInvokeRequest(
                task_name="gmail_message_extract",
                system_prompt="Return JSON object only.",
                user_payload={"message": {"subject": "hello"}},
                output_schema_name="AnyObject",
                output_schema_json={"type": "object"},
                source_id=1,
                request_id="req-1",
                source_provider="gmail",
            ),
        )
        assert len(routes) == 1
        assert routes[0].route_id == "ingestion:env-default:responses:primary"
        assert routes[0].is_fallback is False
    finally:
        get_settings.cache_clear()


def test_judge_profile_uses_dedicated_judge_env_when_present(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "gpt-5-mini")
    monkeypatch.setenv("JUDGE_LLM_BASE_URL", "https://judge.example.com/v1")
    monkeypatch.setenv("JUDGE_LLM_RESPONSES_BASE_URL", "https://judge.example.com/root/responses")
    monkeypatch.setenv("JUDGE_LLM_API_KEY", "judge-key")
    monkeypatch.setenv("JUDGE_LLM_MODEL", "judge-model")
    monkeypatch.setenv("JUDGE_LLM_PROTOCOL", "chat_completions")
    get_settings.cache_clear()
    try:
        profile = resolve_judge_llm_profile()
        assert profile.provider_id == "judge-env-default"
        assert profile.protocol == "chat_completions"
        assert profile.base_url == "https://judge.example.com/v1"
        assert profile.api_key == "judge-key"
        assert profile.model == "judge-model"
    finally:
        get_settings.cache_clear()


def test_judge_profile_falls_back_to_canonical_llm_env_when_unset(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_RESPONSES_BASE_URL", "")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "gpt-5-mini")
    monkeypatch.delenv("JUDGE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("JUDGE_LLM_RESPONSES_BASE_URL", raising=False)
    monkeypatch.delenv("JUDGE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("JUDGE_LLM_MODEL", raising=False)
    monkeypatch.delenv("JUDGE_LLM_PROTOCOL", raising=False)
    get_settings.cache_clear()
    try:
        profile = resolve_judge_llm_profile()
        assert profile.provider_id == "env-default"
        assert profile.protocol == "responses"
        assert profile.base_url == "https://api.openai.com/v1"
        assert profile.model == "gpt-5-mini"
    finally:
        get_settings.cache_clear()


def test_resolve_llm_routes_uses_judge_profile_family(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "gpt-5-mini")
    monkeypatch.setenv("JUDGE_LLM_BASE_URL", "https://judge.example.com/v1")
    monkeypatch.setenv("JUDGE_LLM_API_KEY", "judge-key")
    monkeypatch.setenv("JUDGE_LLM_MODEL", "judge-model")
    get_settings.cache_clear()
    try:
        routes = resolve_llm_routes(
            None,
            invoke_request=LlmInvokeRequest(
                task_name="agent_chain_step_quality_judge",
                system_prompt="Return JSON object only.",
                user_payload={"step": "hello"},
                output_schema_name="AnyObject",
                output_schema_json={"type": "object"},
                profile_family="judge",
                request_id="judge-1",
            ),
        )
        assert len(routes) == 1
        assert routes[0].route_id == "judge:judge-env-default:responses:primary"
        assert routes[0].profile.model == "judge-model"
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("env_name", "expected"),
    (
        ("LLM_BASE_URL", "LLM_BASE_URL is not configured"),
        ("LLM_API_KEY", "LLM_API_KEY is not configured"),
        ("LLM_MODEL", "LLM_MODEL is not configured"),
    ),
)
def test_missing_canonical_llm_env_reports_specific_key(monkeypatch, env_name: str, expected: str) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "gpt-5-mini")
    monkeypatch.setenv(env_name, "")
    get_settings.cache_clear()
    try:
        with pytest.raises(Exception) as exc_info:
            resolve_llm_profile(None, source_id=None)
        assert expected in str(exc_info.value)
    finally:
        get_settings.cache_clear()
