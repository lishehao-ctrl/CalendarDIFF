from __future__ import annotations


def test_register_login_session_logout_flow(input_client, db_session) -> None:
    register_response = input_client.post(
        "/auth/register",
        headers={"X-API-Key": "test-api-key"},
        json={"notify_email": "owner@example.com", "password": "password123"},
    )
    assert register_response.status_code == 201
    assert register_response.json()["authenticated"] is True
    assert register_response.json()["user"]["notify_email"] == "owner@example.com"
    assert "calendardiff_session" in register_response.headers.get("set-cookie", "")

    session_response = input_client.get("/auth/session", headers={"X-API-Key": "test-api-key"})
    assert session_response.status_code == 200
    assert session_response.json()["user"]["notify_email"] == "owner@example.com"
    assert session_response.json()["user"]["onboarding_stage"] == "needs_source_connection"

    logout_response = input_client.post("/auth/logout", headers={"X-API-Key": "test-api-key"})
    assert logout_response.status_code == 200
    assert logout_response.json() == {"logged_out": True}

    after_logout = input_client.get("/auth/session", headers={"X-API-Key": "test-api-key"})
    assert after_logout.status_code == 401

    login_response = input_client.post(
        "/auth/login",
        headers={"X-API-Key": "test-api-key"},
        json={"notify_email": "owner@example.com", "password": "password123"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["authenticated"] is True


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
