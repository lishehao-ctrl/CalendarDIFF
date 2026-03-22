from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.shared import User



def test_get_user_returns_timezone_name(input_client, db_session, auth_headers) -> None:
    user = User(
        email="tz-user@example.com",
        notify_email="tz-user@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()

    headers = auth_headers(input_client, user=user)
    response = input_client.get("/settings/profile", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["timezone_name"] == "UTC"
    assert payload["timezone_source"] == "auto"
    assert payload["language_code"] == "en"



def test_patch_user_timezone_name_validates_iana_name(input_client, db_session, auth_headers) -> None:
    user = User(
        email="tz-user@example.com",
        notify_email="tz-user@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()

    headers = auth_headers(input_client, user=user)

    patch_response = input_client.patch(
        "/settings/profile",
        headers=headers,
        json={"timezone_name": "America/Los_Angeles", "timezone_source": "manual"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["timezone_name"] == "America/Los_Angeles"
    assert patch_response.json()["timezone_source"] == "manual"

    db_session.expire_all()
    refreshed = db_session.scalar(select(User).where(User.id == user.id))
    assert refreshed is not None
    assert refreshed.timezone_name == "America/Los_Angeles"
    assert refreshed.timezone_source == "manual"

    invalid_response = input_client.patch(
        "/settings/profile",
        headers=headers,
        json={"timezone_name": "Mars/Olympus"},
    )
    assert invalid_response.status_code == 422
    assert "timezone_name must be a valid IANA timezone" in str(invalid_response.json()["detail"])



def test_patch_user_auto_timezone_preserves_auto_mode(input_client, db_session, auth_headers) -> None:
    user = User(
        email="tz-auto@example.com",
        notify_email="tz-auto@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()

    headers = auth_headers(input_client, user=user)
    patch_response = input_client.patch(
        "/settings/profile",
        headers=headers,
        json={"timezone_name": "America/New_York", "timezone_source": "auto"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["timezone_name"] == "America/New_York"
    assert patch_response.json()["timezone_source"] == "auto"


def test_patch_user_language_code_persists(input_client, db_session, auth_headers) -> None:
    user = User(
        email="lang-user@example.com",
        notify_email="lang-user@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()

    headers = auth_headers(input_client, user=user)
    patch_response = input_client.patch(
        "/settings/profile",
        headers=headers,
        json={"language_code": "zh-CN"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["language_code"] == "zh-CN"

    db_session.expire_all()
    refreshed = db_session.scalar(select(User).where(User.id == user.id))
    assert refreshed is not None
    assert refreshed.language_code == "zh-CN"

    invalid_response = input_client.patch(
        "/settings/profile",
        headers=headers,
        json={"language_code": "fr"},
    )
    assert invalid_response.status_code == 422
    assert "language_code must be one of: en, zh-CN" in str(invalid_response.json()["detail"])
