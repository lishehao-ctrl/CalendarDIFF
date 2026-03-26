from __future__ import annotations

from app.core.config import get_settings
from app.modules.llm_gateway.contracts import LlmInvokeRequest
from app.modules.llm_gateway.registry import (
    resolve_agent_llm_base_url,
    resolve_agent_llm_profile,
    resolve_llm_base_url,
    resolve_llm_profile,
)
from app.modules.llm_gateway.route_registry import resolve_llm_routes
from app.modules.llm_gateway.transport_gemini_native import build_gemini_native_endpoint
from app.modules.llm_gateway.transport_openai_compat import build_openai_compat_endpoint


def test_named_ingestion_profile_reads_vendor_protocol_and_limits(monkeypatch) -> None:
    monkeypatch.setenv("INGESTION_LLM_PROVIDER_ID", "openai_main")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_VENDOR", "openai")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_PROTOCOL", "chat_completions")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_MODEL", "fallback-model")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_EXTRA_BODY_JSON", '{"enable_thinking":true}')
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_MAX_RETRIES", "2")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_MAX_INPUT_CHARS", "9000")
    get_settings.cache_clear()
    try:
        profile = resolve_llm_profile(None, source_id=None)
        assert profile.vendor == "openai"
        assert profile.protocol == "chat_completions"
        assert profile.model == "fallback-model"
        assert profile.extra_body == {"enable_thinking": True}
        assert profile.timeout_seconds == 30.0
        assert profile.max_retries == 2
        assert profile.max_input_chars == 9000
    finally:
        get_settings.cache_clear()


def test_named_dashscope_profile_uses_mode_specific_responses_base_url(monkeypatch) -> None:
    monkeypatch.setenv("INGESTION_LLM_PROVIDER_ID", "qwen_us_main")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_VENDOR", "dashscope_openai")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_PROTOCOL", "responses")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_BASE_URL", "https://dashscope-us.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv(
        "LLM_PROVIDER_QWEN_US_MAIN_RESPONSES_BASE_URL",
        "https://dashscope-us.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1",
    )
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_MODEL", "test-model")
    get_settings.cache_clear()
    try:
        profile = resolve_llm_profile(None, source_id=None)
        assert profile.vendor == "dashscope_openai"
        assert profile.protocol == "responses"
        assert profile.base_url == "https://dashscope-us.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1"
    finally:
        get_settings.cache_clear()


def test_named_agent_profile_uses_agent_provider_id(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_LLM_PROVIDER_ID", "qwen_us_chat")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_CHAT_VENDOR", "dashscope_openai")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_CHAT_PROTOCOL", "chat_completions")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_CHAT_MODEL", "qwen3.5-plus")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_CHAT_BASE_URL", "https://dashscope-us.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_CHAT_API_KEY", "shared-key")
    get_settings.cache_clear()
    try:
        profile = resolve_agent_llm_profile()
        assert profile.vendor == "dashscope_openai"
        assert profile.protocol == "chat_completions"
        assert profile.model == "qwen3.5-plus"
        assert profile.api_key == "shared-key"
        assert profile.base_url == "https://dashscope-us.aliyuncs.com/compatible-mode/v1"
    finally:
        get_settings.cache_clear()


def test_named_provider_registry_resolves_openai_and_gemini(monkeypatch) -> None:
    monkeypatch.setenv("INGESTION_LLM_PROVIDER_ID", "openai_main")
    monkeypatch.setenv("AGENT_LLM_PROVIDER_ID", "gemini_main")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_VENDOR", "openai")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_PROTOCOL", "responses")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_MODEL", "gpt-5-mini")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_API_KEY", "openai-key")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_MAIN_VENDOR", "gemini")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_MAIN_PROTOCOL", "gemini_generate_content")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_MAIN_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_MAIN_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/models")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_MAIN_API_KEY", "gemini-key")
    get_settings.cache_clear()
    try:
        ingestion = resolve_llm_profile(None, source_id=None)
        agent = resolve_agent_llm_profile()
        assert ingestion.provider_id == "openai_main"
        assert ingestion.vendor == "openai"
        assert ingestion.protocol == "responses"
        assert agent.provider_id == "gemini_main"
        assert agent.vendor == "gemini"
        assert agent.protocol == "gemini_generate_content"
    finally:
        get_settings.cache_clear()


def test_named_provider_routes_stay_within_same_vendor(monkeypatch) -> None:
    monkeypatch.setenv("INGESTION_LLM_PROVIDER_ID", "openai_main")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_VENDOR", "openai")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_PROTOCOL", "responses")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_MODEL", "gpt-5-mini")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_API_KEY", "openai-key")
    monkeypatch.setenv("LLM_PROVIDER_OPENAI_MAIN_FALLBACK_PROVIDER_IDS", "gemini_main")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_MAIN_VENDOR", "gemini")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_MAIN_PROTOCOL", "chat_completions")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_MAIN_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_MAIN_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_MAIN_API_KEY", "gemini-key")
    monkeypatch.setenv("INGESTION_LLM_FALLBACK_ENABLED", "true")
    get_settings.cache_clear()
    try:
        try:
            resolve_llm_routes(
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
        except Exception as exc:
            assert "cross-vendor fallback provider" in str(exc)
        else:
            raise AssertionError("expected cross-vendor fallback config error")
    finally:
        get_settings.cache_clear()


def test_named_provider_routes_include_same_vendor_explicit_fallback_provider(monkeypatch) -> None:
    monkeypatch.setenv("INGESTION_LLM_PROVIDER_ID", "gemini_main")
    monkeypatch.setenv("INGESTION_LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_MAIN_VENDOR", "gemini")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_MAIN_PROTOCOL", "gemini_generate_content")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_MAIN_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_MAIN_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/models")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_MAIN_API_KEY", "gemini-key")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_MAIN_FALLBACK_PROVIDER_IDS", "gemini_compat")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_COMPAT_VENDOR", "gemini")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_COMPAT_PROTOCOL", "chat_completions")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_COMPAT_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_COMPAT_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
    monkeypatch.setenv("LLM_PROVIDER_GEMINI_COMPAT_API_KEY", "gemini-key")
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
            ),
        )
        assert [route.profile.provider_id for route in routes] == ["gemini_main", "gemini_compat"]
        assert [route.profile.protocol for route in routes] == ["gemini_generate_content", "chat_completions"]
    finally:
        get_settings.cache_clear()


def test_named_provider_definition_rejects_unknown_fallback_provider(monkeypatch) -> None:
    monkeypatch.setenv("INGESTION_LLM_PROVIDER_ID", "qwen_us_main")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_VENDOR", "dashscope_openai")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_PROTOCOL", "responses")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_MODEL", "qwen3.5-flash")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_BASE_URL", "https://dashscope-us.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_RESPONSES_BASE_URL", "https://dashscope-us.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_API_KEY", "qwen-key")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_FALLBACK_PROVIDER_IDS", "qwen_missing")
    get_settings.cache_clear()
    try:
        try:
            resolve_llm_profile(None, source_id=None)
        except Exception as exc:
            assert "unknown fallback provider" in str(exc)
        else:
            raise AssertionError("expected unknown fallback provider config error")
    finally:
        get_settings.cache_clear()


def test_qwen_mainline_routes_stay_on_dashscope_without_provider_fallback(monkeypatch) -> None:
    monkeypatch.setenv("INGESTION_LLM_PROVIDER_ID", "qwen_us_main")
    monkeypatch.setenv("INGESTION_LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_VENDOR", "dashscope_openai")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_PROTOCOL", "responses")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_MODEL", "qwen3.5-flash")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_BASE_URL", "https://dashscope-us.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_RESPONSES_BASE_URL", "https://dashscope-us.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_CHAT_BASE_URL", "https://dashscope-us.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_API_KEY", "qwen-key")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_FALLBACK_PROVIDER_IDS", "")
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
                request_id="req-qwen-mainline",
                source_provider="gmail",
            ),
        )
        assert [route.profile.vendor for route in routes] == ["dashscope_openai", "dashscope_openai"]
        assert [route.profile.provider_id for route in routes] == ["qwen_us_main", "qwen_us_main"]
        assert [route.profile.protocol for route in routes] == ["responses", "chat_completions"]
    finally:
        get_settings.cache_clear()


def test_build_openai_compat_endpoint_uses_protocol_suffixes() -> None:
    assert build_openai_compat_endpoint(base_url="https://api.openai.com/v1", protocol="responses") == "https://api.openai.com/v1/responses"
    assert build_openai_compat_endpoint(base_url="https://api.openai.com/v1", protocol="chat_completions") == "https://api.openai.com/v1/chat/completions"


def test_build_gemini_native_endpoint_uses_model_suffixes() -> None:
    assert (
        build_gemini_native_endpoint(
            base_url="https://generativelanguage.googleapis.com/v1beta/models",
            model="gemini-2.5-flash",
            stream=False,
        )
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    )
    assert (
        build_gemini_native_endpoint(
            base_url="https://generativelanguage.googleapis.com/v1beta/models",
            model="gemini-2.5-flash",
            stream=True,
        )
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent?alt=sse"
    )


def test_resolve_agent_llm_base_url_named_provider(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_VENDOR", "dashscope_openai")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_PROTOCOL", "responses")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_MODEL", "qwen3.5-plus")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_BASE_URL", "https://dashscope-us.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_API_KEY", "qwen-key")
    monkeypatch.setenv("LLM_PROVIDER_QWEN_US_MAIN_RESPONSES_BASE_URL", "https://dashscope-us.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1")
    get_settings.cache_clear()
    try:
        base_url = resolve_agent_llm_base_url(protocol="responses", provider_id="qwen_us_main")
        assert base_url == "https://dashscope-us.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1"
    finally:
        get_settings.cache_clear()
