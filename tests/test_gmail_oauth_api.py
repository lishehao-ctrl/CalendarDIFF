from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.core.config import get_settings
from app.db.models import InputType, User
from app.modules.inputs.schemas import InputCreateRequest
from app.modules.inputs.service import (
    build_gmail_oauth_start,
    create_gmail_input_from_oauth,
    create_ics_input,
    parse_gmail_oauth_state,
)
from app.modules.sync.gmail_client import GmailOAuthTokens, GmailProfile


DEFAULT_REDIRECT_URI = "http://localhost:8000/v1/oauth/gmail/callback"


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


def _default_client_secrets_payload(
    *,
    client_id: str = "client-id",
    client_secret: str = "client-secret",
    redirect_uri: str = DEFAULT_REDIRECT_URI,
) -> dict[str, object]:
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": [redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def _write_client_secrets_file(
    tmp_path: Path,
    *,
    payload: dict[str, object] | None = None,
    as_jsonl: bool = False,
    file_name: str | None = None,
    mode: int = 0o600,
) -> Path:
    data = payload or _default_client_secrets_payload()
    name = file_name or ("client_secret.jsonl" if as_jsonl else "client_secret.json")
    path = tmp_path / name
    if as_jsonl:
        path.write_text(f"{json.dumps(data, separators=(',', ':'))}\n", encoding="utf-8")
    else:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if os.name != "nt":
        os.chmod(path, mode)
    return path


def _set_oauth_client_secrets_env(monkeypatch, path: str) -> None:
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_SECRETS_FILE", path)
    monkeypatch.delenv("GMAIL_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GMAIL_OAUTH_REDIRECT_URI", raising=False)


def test_gmail_oauth_start_requires_initialized_user(client, monkeypatch, tmp_path) -> None:
    secrets_file = _write_client_secrets_file(tmp_path)
    _set_oauth_client_secrets_env(monkeypatch, str(secrets_file))
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
    monkeypatch.delenv("GMAIL_OAUTH_CLIENT_SECRETS_FILE", raising=False)
    get_settings.cache_clear()
    _init_user(client, db_session)

    response = client.post(
        "/v1/inputs/email/gmail/oauth/start",
        headers={"X-API-Key": "test-api-key"},
        json={},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Gmail OAuth client secrets file is not configured"

    get_settings.cache_clear()


def test_gmail_oauth_start_ignores_legacy_oauth_env_vars(client, db_session, monkeypatch) -> None:
    monkeypatch.delenv("GMAIL_OAUTH_CLIENT_SECRETS_FILE", raising=False)
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_ID", "legacy-client-id")
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_SECRET", "legacy-client-secret")
    monkeypatch.setenv("GMAIL_OAUTH_REDIRECT_URI", DEFAULT_REDIRECT_URI)
    get_settings.cache_clear()
    _init_user(client, db_session)

    response = client.post(
        "/v1/inputs/email/gmail/oauth/start",
        headers={"X-API-Key": "test-api-key"},
        json={},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Gmail OAuth client secrets file is not configured"

    get_settings.cache_clear()


def test_gmail_oauth_start_returns_authorization_url(client, db_session, monkeypatch, tmp_path) -> None:
    secrets_file = _write_client_secrets_file(tmp_path)
    _set_oauth_client_secrets_env(monkeypatch, str(secrets_file))
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
    assert query["redirect_uri"] == [DEFAULT_REDIRECT_URI]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert "state" in query and query["state"][0]
    oauth_state = parse_gmail_oauth_state(query["state"][0])
    assert oauth_state.label == "INBOX"
    assert oauth_state.from_contains == "instructor@school.edu"
    assert oauth_state.subject_keywords == ["assignment", "deadline"]
    assert not hasattr(oauth_state, "profile_id")

    get_settings.cache_clear()


def test_gmail_oauth_start_supports_single_record_jsonl(client, db_session, monkeypatch, tmp_path) -> None:
    secrets_file = _write_client_secrets_file(tmp_path, as_jsonl=True)
    _set_oauth_client_secrets_env(monkeypatch, str(secrets_file))
    get_settings.cache_clear()
    _init_user(client, db_session)

    response = client.post(
        "/v1/inputs/email/gmail/oauth/start",
        headers={"X-API-Key": "test-api-key"},
        json={},
    )
    assert response.status_code == 200

    query = parse_qs(urlparse(response.json()["authorization_url"]).query)
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == [DEFAULT_REDIRECT_URI]

    get_settings.cache_clear()


def test_gmail_oauth_start_rejects_repo_local_client_secrets_file(client, db_session, monkeypatch) -> None:
    repo_local_file = Path("README.md").resolve()
    _set_oauth_client_secrets_env(monkeypatch, str(repo_local_file))
    get_settings.cache_clear()
    _init_user(client, db_session)

    response = client.post(
        "/v1/inputs/email/gmail/oauth/start",
        headers={"X-API-Key": "test-api-key"},
        json={},
    )
    assert response.status_code == 503
    assert "outside the repository" in response.json()["detail"].lower()

    get_settings.cache_clear()


def test_gmail_oauth_start_rejects_permissive_client_secrets_file(client, db_session, monkeypatch, tmp_path) -> None:
    if os.name == "nt":
        return

    secrets_file = _write_client_secrets_file(tmp_path, mode=0o644)
    _set_oauth_client_secrets_env(monkeypatch, str(secrets_file))
    get_settings.cache_clear()
    _init_user(client, db_session)

    response = client.post(
        "/v1/inputs/email/gmail/oauth/start",
        headers={"X-API-Key": "test-api-key"},
        json={},
    )
    assert response.status_code == 503
    assert "permissions are too open" in response.json()["detail"].lower()

    get_settings.cache_clear()


def test_gmail_oauth_start_rejects_invalid_client_secrets_payload(client, db_session, monkeypatch, tmp_path) -> None:
    invalid_file = tmp_path / "client_secret.jsonl"
    invalid_file.write_text("not-json\nsecond-line\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(invalid_file, 0o600)

    _set_oauth_client_secrets_env(monkeypatch, str(invalid_file))
    get_settings.cache_clear()
    _init_user(client, db_session)

    response = client.post(
        "/v1/inputs/email/gmail/oauth/start",
        headers={"X-API-Key": "test-api-key"},
        json={},
    )
    assert response.status_code == 503
    assert "content is invalid" in response.json()["detail"].lower()

    get_settings.cache_clear()


def test_gmail_oauth_start_rejects_legacy_interval_or_notify_fields(client, db_session, monkeypatch, tmp_path) -> None:
    secrets_file = _write_client_secrets_file(tmp_path)
    _set_oauth_client_secrets_env(monkeypatch, str(secrets_file))
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


def test_gmail_oauth_callback_creates_email_input_and_redirects(client, db_session, monkeypatch, tmp_path) -> None:
    secrets_file = _write_client_secrets_file(tmp_path)
    _set_oauth_client_secrets_env(monkeypatch, str(secrets_file))
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
    redirect_parsed = urlparse(redirect_url)
    assert redirect_parsed.path == "/ui/inputs"
    redirect_query = parse_qs(redirect_parsed.query)
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


def test_create_gmail_input_keeps_existing_refresh_token_when_oauth_response_has_no_refresh_token(
    client,
    db_session,
) -> None:
    _init_user(client, db_session)
    user = db_session.query(User).order_by(User.id.asc()).first()
    assert user is not None

    first = create_gmail_input_from_oauth(
        db_session,
        user_id=user.id,
        label="INBOX",
        from_contains=None,
        subject_keywords=["deadline"],
        account_email="student@example.com",
        history_id=None,
        access_token="access-token-1",
        refresh_token="refresh-token-1",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    first_refresh_token = first.input.encrypted_refresh_token
    assert first_refresh_token is not None

    second = create_gmail_input_from_oauth(
        db_session,
        user_id=user.id,
        label="INBOX",
        from_contains=None,
        subject_keywords=["deadline"],
        account_email="student@example.com",
        history_id="123",
        access_token="access-token-2",
        refresh_token=None,
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert second.upserted_existing is True
    assert second.input.encrypted_refresh_token == first_refresh_token


def test_gmail_oauth_callback_requires_refresh_token_for_new_input(client, db_session, monkeypatch, tmp_path) -> None:
    secrets_file = _write_client_secrets_file(tmp_path)
    _set_oauth_client_secrets_env(monkeypatch, str(secrets_file))
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
            refresh_token=None,
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
    redirect_query = parse_qs(urlparse(response.headers["location"]).query)
    assert redirect_query["gmail_oauth_status"] == ["error"]
    assert "refresh token" in redirect_query.get("message", [""])[0].lower()

    inputs_response = client.get("/v1/inputs", headers={"X-API-Key": "test-api-key"})
    assert inputs_response.status_code == 200
    rows = inputs_response.json()
    assert [row for row in rows if row["type"] == InputType.EMAIL.value] == []

    get_settings.cache_clear()
