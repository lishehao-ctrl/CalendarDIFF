from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text, select

from app.core.config import get_settings
from app.db.models.shared import User
from app.db.session import reset_engine
from app.modules.auth.service import _hash_password


def test_register_login_session_logout_flow(input_client, db_session) -> None:
    register_response = input_client.post(
        "/auth/register",
        headers={"X-API-Key": "test-api-key"},
        json={"notify_email": "owner@example.com", "password": "password123", "timezone_name": "America/Los_Angeles"},
    )
    assert register_response.status_code == 201
    assert register_response.json()["authenticated"] is True
    assert register_response.json()["user"]["notify_email"] == "owner@example.com"
    assert register_response.json()["user"]["timezone_name"] == "America/Los_Angeles"
    assert register_response.json()["user"]["timezone_source"] == "auto"
    assert "calendardiff_session" in register_response.headers.get("set-cookie", "")

    session_response = input_client.get("/auth/session", headers={"X-API-Key": "test-api-key"})
    assert session_response.status_code == 200
    assert session_response.json()["user"]["notify_email"] == "owner@example.com"
    assert session_response.json()["user"]["timezone_name"] == "America/Los_Angeles"
    assert session_response.json()["user"]["onboarding_stage"] == "needs_canvas_ics"

    logout_response = input_client.post("/auth/logout", headers={"X-API-Key": "test-api-key"})
    assert logout_response.status_code == 200
    assert logout_response.json() == {"logged_out": True}

    after_logout = input_client.get("/auth/session", headers={"X-API-Key": "test-api-key"})
    assert after_logout.status_code == 401

    login_response = input_client.post(
        "/auth/login",
        headers={"X-API-Key": "test-api-key"},
        json={"notify_email": "owner@example.com", "password": "password123", "timezone_name": "America/Chicago"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["authenticated"] is True
    assert login_response.json()["user"]["timezone_name"] == "America/Chicago"

    db_session.expire_all()
    refreshed = db_session.scalar(select(User).where(User.notify_email == "owner@example.com"))
    assert refreshed is not None
    assert refreshed.timezone_name == "America/Chicago"
    assert refreshed.timezone_source == "auto"


def test_login_invalid_password_returns_401(input_client, db_session) -> None:
    register_response = input_client.post(
        "/auth/register",
        headers={"X-API-Key": "test-api-key"},
        json={"notify_email": "owner@example.com", "password": "password123"},
    )
    assert register_response.status_code == 201
    input_client.cookies.clear()

    response = input_client.post(
        "/auth/login",
        headers={"X-API-Key": "test-api-key"},
        json={"notify_email": "owner@example.com", "password": "wrong-pass"},
    )
    assert response.status_code == 401


def test_login_allows_existing_bootstrap_short_password(input_client, db_session) -> None:
    user = User(
        email="lishehao@gmail.com",
        notify_email="lishehao@gmail.com",
        password_hash=_hash_password("123456"),
        timezone_name="America/Los_Angeles",
        timezone_source="manual",
        onboarding_completed_at=None,
    )
    db_session.add(user)
    db_session.commit()

    response = input_client.post(
        "/auth/login",
        headers={"X-API-Key": "test-api-key"},
        json={"notify_email": "lishehao@gmail.com", "password": "123456"},
    )

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["user"]["notify_email"] == "lishehao@gmail.com"


def test_login_does_not_override_manual_timezone(input_client, db_session) -> None:
    register_response = input_client.post(
        "/auth/register",
        headers={"X-API-Key": "test-api-key"},
        json={"notify_email": "manual-owner@example.com", "password": "password123", "timezone_name": "UTC"},
    )
    assert register_response.status_code == 201
    input_client.cookies.clear()

    user = db_session.scalar(select(User).where(User.notify_email == "manual-owner@example.com"))
    assert user is not None
    user.timezone_name = "UTC"
    user.timezone_source = "manual"
    db_session.commit()

    login_response = input_client.post(
        "/auth/login",
        headers={"X-API-Key": "test-api-key"},
        json={"notify_email": "manual-owner@example.com", "password": "password123", "timezone_name": "America/New_York"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["user"]["timezone_name"] == "UTC"
    assert login_response.json()["user"]["timezone_source"] == "manual"


def test_register_returns_503_when_schema_shape_is_stamped_but_incomplete(db_engine) -> None:
    with db_engine.begin() as conn:
        conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS timezone_source"))

    get_settings.cache_clear()
    reset_engine()
    from services.app_api.main import app as public_api_app

    try:
        with TestClient(public_api_app) as client:
            response = client.post(
                "/auth/register",
                headers={"X-API-Key": "test-api-key"},
                json={"notify_email": "schema-broken@example.com", "password": "password123", "timezone_name": "America/Los_Angeles"},
            )
        assert response.status_code == 503
        assert "Database schema is not ready for this app version." in response.json()["detail"]
        assert "missing columns: users.timezone_source" in response.json()["detail"]
    finally:
        with db_engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone_source VARCHAR(32) NOT NULL DEFAULT 'manual'"))
        get_settings.cache_clear()
        reset_engine()
