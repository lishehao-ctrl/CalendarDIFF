from __future__ import annotations

from app.core.config import get_settings
from urllib.parse import parse_qs, urlparse

import pytest

from app.modules.sync.gmail_client import GmailClient, GmailOAuthClientSecrets


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


def test_gmail_client_uses_runtime_oauth_parameters(monkeypatch) -> None:
    monkeypatch.setenv("OAUTH_PUBLIC_BASE_URL", "http://localhost:8001")
    monkeypatch.setenv("GMAIL_OAUTH_SCOPE", "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/userinfo.email")
    monkeypatch.setenv("GMAIL_OAUTH_ACCESS_TYPE", "online")
    monkeypatch.setenv("GMAIL_OAUTH_PROMPT", "select_account")
    monkeypatch.setenv("GMAIL_OAUTH_INCLUDE_GRANTED_SCOPES", "false")
    get_settings.cache_clear()

    client = GmailClient()
    monkeypatch.setattr(
        client,
        "_load_oauth_client_secrets",
        lambda: GmailOAuthClientSecrets(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uris=("http://localhost:8001/oauth/callbacks/gmail",),
        ),
    )

    authorization_url = client.build_authorization_url(state="state-123")
    query = parse_qs(urlparse(authorization_url).query)

    assert query["redirect_uri"] == ["http://localhost:8001/oauth/callbacks/gmail"]
    assert query["scope"] == ["https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/userinfo.email"]
    assert query["access_type"] == ["online"]
    assert query["prompt"] == ["select_account"]
    assert query["include_granted_scopes"] == ["false"]
    get_settings.cache_clear()


def test_gmail_client_rejects_redirect_uri_not_registered(monkeypatch) -> None:
    monkeypatch.setenv("OAUTH_PUBLIC_BASE_URL", "http://localhost:8001")
    get_settings.cache_clear()

    client = GmailClient()
    monkeypatch.setattr(
        client,
        "_load_oauth_client_secrets",
        lambda: GmailOAuthClientSecrets(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uris=("http://localhost:9999/oauth/callbacks/gmail",),
        ),
    )

    with pytest.raises(RuntimeError, match="not registered"):
        client.build_authorization_url(state="state-abc")
    get_settings.cache_clear()
