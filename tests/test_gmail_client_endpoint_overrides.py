from __future__ import annotations

from app.core.config import get_settings
from app.modules.sync.gmail_client import GmailClient


def test_gmail_client_uses_default_endpoints(monkeypatch) -> None:
    monkeypatch.delenv("GMAIL_API_BASE_URL", raising=False)
    monkeypatch.delenv("GMAIL_OAUTH_TOKEN_URL", raising=False)
    monkeypatch.delenv("GMAIL_OAUTH_AUTHORIZE_URL", raising=False)
    get_settings.cache_clear()

    client = GmailClient()

    assert client._gmail_api_base == "https://gmail.googleapis.com/gmail/v1/users/me"
    assert client._oauth_token_url == "https://oauth2.googleapis.com/token"
    assert client._oauth_authorize_url == "https://accounts.google.com/o/oauth2/v2/auth"
    get_settings.cache_clear()


def test_gmail_client_honors_endpoint_overrides(monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_API_BASE_URL", "http://127.0.0.1:8765/gmail/v1/users/me/")
    monkeypatch.setenv("GMAIL_OAUTH_TOKEN_URL", "http://127.0.0.1:8765/oauth2/token/")
    monkeypatch.setenv("GMAIL_OAUTH_AUTHORIZE_URL", "http://127.0.0.1:8765/oauth2/auth/")
    get_settings.cache_clear()

    client = GmailClient()

    assert client._gmail_api_base == "http://127.0.0.1:8765/gmail/v1/users/me"
    assert client._oauth_token_url == "http://127.0.0.1:8765/oauth2/token"
    assert client._oauth_authorize_url == "http://127.0.0.1:8765/oauth2/auth"
    get_settings.cache_clear()
