from __future__ import annotations

from app.core.config import get_settings
from app.modules.llm_gateway.registry import resolve_llm_profile


def test_resolve_llm_profile_falls_back_to_app_openai_model(monkeypatch) -> None:
    monkeypatch.setenv("INGESTION_LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("INGESTION_LLM_API_KEY", "test-key")
    monkeypatch.setenv("INGESTION_LLM_MODEL", "")
    monkeypatch.setenv("APP_LLM_OPENAI_MODEL", "fallback-model")
    get_settings.cache_clear()
    try:
        profile = resolve_llm_profile(None, source_id=None)
        assert profile.model == "fallback-model"
    finally:
        get_settings.cache_clear()
