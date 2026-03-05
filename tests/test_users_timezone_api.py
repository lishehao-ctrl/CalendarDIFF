from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.shared import User


def test_get_user_returns_timezone_name(input_client, db_session) -> None:
    user = User(
        email="tz-user@example.com",
        notify_email="tz-user@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()

    response = input_client.get("/users/me", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["timezone_name"] == "UTC"


def test_patch_user_timezone_name_validates_iana_name(input_client, db_session) -> None:
    user = User(
        email="tz-user@example.com",
        notify_email="tz-user@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()

    patch_response = input_client.patch(
        "/users/me",
        headers={"X-API-Key": "test-api-key"},
        json={"timezone_name": "America/Los_Angeles"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["timezone_name"] == "America/Los_Angeles"

    db_session.expire_all()
    refreshed = db_session.scalar(select(User).where(User.id == user.id))
    assert refreshed is not None
    assert refreshed.timezone_name == "America/Los_Angeles"

    invalid_response = input_client.patch(
        "/users/me",
        headers={"X-API-Key": "test-api-key"},
        json={"timezone_name": "Mars/Olympus"},
    )
    assert invalid_response.status_code == 422
    assert "timezone_name must be a valid IANA timezone" in str(invalid_response.json()["detail"])
