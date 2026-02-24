from __future__ import annotations


def _init_user(client) -> None:
    response = client.post(
        "/v1/user",
        headers={"X-API-Key": "test-api-key"},
        json={"notify_email": "student@example.com"},
    )
    assert response.status_code in {200, 201}


def test_notification_prefs_require_initialized_user(client) -> None:
    response = client.get("/v1/notification_prefs", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "user_not_initialized"


def test_notification_prefs_get_defaults(client) -> None:
    _init_user(client)
    response = client.get("/v1/notification_prefs", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["digest_enabled"] is True
    assert payload["timezone"] == "America/Los_Angeles"
    assert payload["digest_times"] == ["09:00"]


def test_notification_prefs_put_normalizes_times(client) -> None:
    _init_user(client)
    response = client.put(
        "/v1/notification_prefs",
        headers={"X-API-Key": "test-api-key"},
        json={
            "digest_enabled": True,
            "timezone": "America/Los_Angeles",
            "digest_times": ["21:30", "09:00", "09:00"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["digest_times"] == ["09:00", "21:30"]


def test_notification_prefs_put_rejects_invalid_times(client) -> None:
    _init_user(client)
    response = client.put(
        "/v1/notification_prefs",
        headers={"X-API-Key": "test-api-key"},
        json={
            "digest_times": ["25:61"],
        },
    )
    assert response.status_code == 422
