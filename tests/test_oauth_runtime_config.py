from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.core.oauth_config import (
    build_frontend_sources_return_url,
    build_oauth_runtime_config,
    resolve_frontend_app_base_url,
    resolve_oauth_token_encryption_key,
)


def test_oauth_runtime_defaults_fallback_and_deterministic(monkeypatch) -> None:
    monkeypatch.setenv("OAUTH_PUBLIC_BASE_URL", "")
    monkeypatch.setenv("APP_BASE_URL", "")
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "")
    monkeypatch.delenv("OAUTH_ROUTE_PREFIX", raising=False)
    monkeypatch.delenv("OAUTH_TOKEN_ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()

    runtime_a = build_oauth_runtime_config()
    runtime_b = build_oauth_runtime_config()

    assert runtime_a == runtime_b
    assert runtime_a.public_base_url == "http://localhost:8200"
    assert runtime_a.oauth_session_route_path == "/sources/{source_id}/oauth-sessions"
    assert runtime_a.callback_route_path == "/oauth/callbacks/{provider}"
    assert runtime_a.gmail_redirect_uri == "http://localhost:8200/oauth/callbacks/gmail"
    assert runtime_a.token_encryption_key_source == "APP_SECRET_KEY"
    get_settings.cache_clear()


def test_oauth_runtime_base_url_priority_and_normalization(monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "http://127.0.0.1:8200/")
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:9000/app/")
    monkeypatch.setenv("OAUTH_PUBLIC_BASE_URL", "https://oauth.example.com/root/")
    get_settings.cache_clear()

    runtime = build_oauth_runtime_config()

    assert runtime.public_base_url == "https://oauth.example.com/root"
    assert runtime.gmail_redirect_uri == "https://oauth.example.com/root/oauth/callbacks/gmail"
    get_settings.cache_clear()


def test_oauth_runtime_route_prefix_join(monkeypatch) -> None:
    monkeypatch.setenv("OAUTH_ROUTE_PREFIX", "api")
    monkeypatch.setenv("OAUTH_SESSION_ROUTE_TEMPLATE", "/sources/{source_id}/oauth-sessions")
    monkeypatch.setenv("OAUTH_CALLBACK_ROUTE_TEMPLATE", "/oauth/callbacks/{provider}")
    get_settings.cache_clear()

    runtime = build_oauth_runtime_config()

    assert runtime.route_prefix == "/api"
    assert runtime.oauth_session_route_path == "/api/sources/{source_id}/oauth-sessions"
    assert runtime.callback_route_path == "/api/oauth/callbacks/{provider}"
    assert runtime.callback_route_for_provider("gmail") == "/api/oauth/callbacks/gmail"
    get_settings.cache_clear()


def test_oauth_runtime_callback_require_api_key_is_forbidden(monkeypatch) -> None:
    monkeypatch.setenv("OAUTH_CALLBACK_REQUIRE_API_KEY", "true")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="cannot require API key"):
        build_oauth_runtime_config()
    get_settings.cache_clear()


def test_oauth_token_encryption_key_source_priority(monkeypatch) -> None:
    override_key = "mSlJfqbS1h0UAb3DH6m3H8dzW4z6utidqKl15Jjlv1A="
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", override_key)
    get_settings.cache_clear()

    key, source = resolve_oauth_token_encryption_key()

    assert key == override_key
    assert source == "OAUTH_TOKEN_ENCRYPTION_KEY"
    get_settings.cache_clear()


def test_frontend_app_base_url_priority_and_return_url(monkeypatch) -> None:
    monkeypatch.setenv("FRONTEND_APP_BASE_URL", "https://console.example.com/app/")
    monkeypatch.setenv("PUBLIC_WEB_ORIGINS", "http://localhost:8200,http://127.0.0.1:8200")
    get_settings.cache_clear()

    assert resolve_frontend_app_base_url() == "https://console.example.com/app"
    assert build_frontend_sources_return_url(
        oauth_provider="gmail",
        oauth_status="success",
        source_id=42,
        request_id="sync-req-1",
        message="oauth callback processed",
    ) == (
        "https://console.example.com/app/sources?"
        "oauth_provider=gmail&oauth_status=success&source_id=42&request_id=sync-req-1&message=oauth+callback+processed"
    )
    get_settings.cache_clear()


def test_frontend_app_base_url_falls_back_to_first_public_origin(monkeypatch) -> None:
    monkeypatch.delenv("FRONTEND_APP_BASE_URL", raising=False)
    monkeypatch.setenv("PUBLIC_WEB_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    get_settings.cache_clear()

    assert resolve_frontend_app_base_url() == "http://127.0.0.1:3000"
    get_settings.cache_clear()
