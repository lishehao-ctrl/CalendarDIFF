from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import User


def test_user_get_404_until_registered(client) -> None:
    headers = {"X-API-Key": "test-api-key"}

    get_before = client.get("/v1/user", headers=headers)
    assert get_before.status_code == 404
    assert get_before.json()["detail"]["code"] == "user_not_initialized"


def test_user_patch_updates_existing_user(client, db_session) -> None:
    headers = {"X-API-Key": "test-api-key"}
    user = User(
        email="legacy@example.com",
        notify_email="student-a@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()

    patch_response = client.patch(
        "/v1/user",
        headers=headers,
        json={"notify_email": "student-b@example.com", "calendar_delay_seconds": 300},
    )
    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["notify_email"] == "student-b@example.com"
    assert payload["calendar_delay_seconds"] == 300
