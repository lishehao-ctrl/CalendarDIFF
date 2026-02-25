from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from app.core.config import get_settings
from app.db.models import User
from app.modules.inputs.schemas import InputCreateRequest
from app.modules.inputs.service import build_gmail_oauth_start, create_ics_input, parse_gmail_oauth_state
from app.modules.sync.gmail_client import GmailOAuthTokens, GmailProfile


def _init_user(client, db_session) -> None:
    del client
    user = User(
        email=None,
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    create_ics_input(
        db_session,
        user_id=user.id,
        payload=InputCreateRequest(url="https://example.com/gmail-oauth-onboarded.ics"),
    )
    db_session.commit()


def test_gmail_oauth_start_requires_initialized_user(client, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GMAIL_OAUTH_REDIRECT_URI", "http://localhost:8000/v1/oauth/gmail/callback")
    get_settings.cache_clear()

    response = client.post(
        "/v1/inputs/email/gmail/oauth/start",
        headers={"X-API-Key": "test-api-key"},
        json={},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "user_not_initialized"

    get_settings.cache_clear()


def test_gmail_oauth_start_requires_configuration(client, db_session, monkeypatch) -> None:
    monkeypatch.delenv("GMAIL_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GMAIL_OAUTH_REDIRECT_URI", raising=False)
    get_settings.cache_clear()
    _init_user(client, db_session)

    response = client.post(
        "/v1/inputs/email/gmail/oauth/start",
        headers={"X-API-Key": "test-api-key"},
        json={},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Gmail OAuth is not configured"

    get_settings.cache_clear()


def test_gmail_oauth_start_returns_authorization_url(client, db_session, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GMAIL_OAUTH_REDIRECT_URI", "http://localhost:8000/v1/oauth/gmail/callback")
    get_settings.cache_clear()
    _init_user(client, db_session)

    response = client.post(
        "/v1/inputs/email/gmail/oauth/start",
        headers={"X-API-Key": "test-api-key"},
        json={
            "label": "INBOX",
            "from_contains": "instructor@school.edu",
            "subject_keywords": ["assignment", "deadline"],
        },
    )
    assert response.status_code == 200

    payload = response.json()
    assert "authorization_url" in payload
    assert "expires_at" in payload

    parsed = urlparse(payload["authorization_url"])
    query = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["http://localhost:8000/v1/oauth/gmail/callback"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert "state" in query and query["state"][0]
    oauth_state = parse_gmail_oauth_state(query["state"][0])
    assert oauth_state.label == "INBOX"
    assert oauth_state.from_contains == "instructor@school.edu"
    assert oauth_state.subject_keywords == ["assignment", "deadline"]
    assert not hasattr(oauth_state, "profile_id")

    get_settings.cache_clear()


def test_gmail_oauth_start_rejects_legacy_interval_or_notify_fields(client, db_session, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GMAIL_OAUTH_REDIRECT_URI", "http://localhost:8000/v1/oauth/gmail/callback")
    get_settings.cache_clear()
    _init_user(client, db_session)

    with_interval = client.post(
        "/v1/inputs/email/gmail/oauth/start",
        headers={"X-API-Key": "test-api-key"},
        json={"interval_minutes": 10},
    )
    assert with_interval.status_code == 422

    with_notify = client.post(
        "/v1/inputs/email/gmail/oauth/start",
        headers={"X-API-Key": "test-api-key"},
        json={"notify_email": "legacy@example.com"},
    )
    assert with_notify.status_code == 422

    get_settings.cache_clear()


def test_gmail_oauth_callback_creates_email_input_and_redirects(client, db_session, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GMAIL_OAUTH_REDIRECT_URI", "http://localhost:8000/v1/oauth/gmail/callback")
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:8000")
    get_settings.cache_clear()
    _init_user(client, db_session)

    oauth_start = build_gmail_oauth_start(
        label="INBOX",
        from_contains="instructor@school.edu",
        subject_keywords=["assignment", "quiz"],
    )
    state = parse_qs(urlparse(oauth_start.authorization_url).query)["state"][0]

    def fake_exchange_code(self, *, code: str) -> GmailOAuthTokens:  # noqa: ANN001
        assert code == "oauth-code"
        return GmailOAuthTokens(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    def fake_get_profile(self, *, access_token: str) -> GmailProfile:  # noqa: ANN001
        assert access_token == "access-token"
        return GmailProfile(email_address="student@example.com", history_id="9001")

    monkeypatch.setattr("app.modules.oauth.router.GmailClient.exchange_code", fake_exchange_code)
    monkeypatch.setattr("app.modules.oauth.router.GmailClient.get_profile", fake_get_profile)

    response = client.get(
        "/v1/oauth/gmail/callback",
        params={"code": "oauth-code", "state": state},
        follow_redirects=False,
    )
    assert response.status_code == 302

    redirect_url = response.headers["location"]
    redirect_query = parse_qs(urlparse(redirect_url).query)
    assert redirect_query["gmail_oauth_status"] == ["success"]
    assert "input_id" in redirect_query

    inputs_response = client.get("/v1/inputs", headers={"X-API-Key": "test-api-key"})
    assert inputs_response.status_code == 200
    rows = inputs_response.json()
    assert len(rows) == 2
    input_row = next(row for row in rows if row["type"] == "email")
    assert input_row["type"] == "email"
    assert input_row["provider"] == "gmail"
    assert input_row["gmail_label"] == "INBOX"
    assert input_row["gmail_from_contains"] == "instructor@school.edu"
    assert input_row["gmail_subject_keywords"] == ["assignment", "quiz"]
    assert input_row["gmail_account_email"] == "student@example.com"

    get_settings.cache_clear()
