from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import User


def _init_user(client, db_session) -> None:
    del client
    user = User(
        email=None,
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()


def test_notification_prefs_require_initialized_user(client) -> None:
    response = client.get("/v1/notification_prefs", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "user_not_initialized"


def test_notification_prefs_get_defaults(client, db_session) -> None:
    _init_user(client, db_session)
    response = client.get("/v1/notification_prefs", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["digest_enabled"] is True
    assert payload["timezone"] == "America/Los_Angeles"
    assert payload["digest_times"] == ["09:00"]


def test_notification_prefs_put_normalizes_times(client, db_session) -> None:
    _init_user(client, db_session)
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


def test_notification_prefs_put_rejects_invalid_times(client, db_session) -> None:
    _init_user(client, db_session)
    response = client.put(
        "/v1/notification_prefs",
        headers={"X-API-Key": "test-api-key"},
        json={
            "digest_times": ["25:61"],
        },
    )
    assert response.status_code == 422
