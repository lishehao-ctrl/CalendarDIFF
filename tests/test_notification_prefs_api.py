from __future__ import annotations


def test_notification_prefs_get_defaults(client) -> None:
    response = client.get("/v1/notification_prefs", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["digest_enabled"] is True
    assert payload["timezone"] == "America/Los_Angeles"
    assert payload["digest_times"] == ["09:00"]


def test_notification_prefs_put_normalizes_times(client) -> None:
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
    response = client.put(
        "/v1/notification_prefs",
        headers={"X-API-Key": "test-api-key"},
        json={
            "digest_times": ["25:61"],
        },
    )
    assert response.status_code == 422
