from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.input import InputSource
from app.db.models.shared import User


def _create_user(db_session, *, email: str) -> User:
    user = User(
        email=None,
        notify_email=email,
        password_hash="hash",
        timezone_name="America/Los_Angeles",
        timezone_source="manual",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_onboarding_progresses_from_canvas_to_skip_to_monitoring_ready(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session, email="onboarding-flow@example.com")
    authenticate_client(input_client, user=user)

    status_response = input_client.get("/onboarding/status", headers={"X-API-Key": "test-api-key"})
    assert status_response.status_code == 200
    assert status_response.json()["stage"] == "needs_canvas_ics"

    canvas_response = input_client.post(
        "/onboarding/canvas-ics",
        headers={"X-API-Key": "test-api-key"},
        json={"url": "https://example.com/onboarding.ics"},
    )
    assert canvas_response.status_code == 200
    assert canvas_response.json()["stage"] == "needs_gmail_or_skip"
    assert canvas_response.json()["canvas_source"]["connected"] is True

    skip_response = input_client.post(
        "/onboarding/gmail-skip",
        headers={"X-API-Key": "test-api-key"},
        json={},
    )
    assert skip_response.status_code == 200
    assert skip_response.json()["stage"] == "needs_monitoring_window"
    assert skip_response.json()["gmail_skipped"] is True

    term_response = input_client.post(
        "/onboarding/monitoring-window",
        headers={"X-API-Key": "test-api-key"},
        json={"monitor_since": "2026-01-05"},
    )
    assert term_response.status_code == 200
    payload = term_response.json()
    assert payload["stage"] == "ready"
    assert payload["monitoring_window"] == {
        "monitor_since": "2026-01-05",
    }

    db_session.expire_all()
    source = db_session.scalar(select(InputSource).where(InputSource.user_id == user.id, InputSource.provider == "ics"))
    assert source is not None
    assert source.is_active is True
    assert source.config is not None
    assert source.config.config_json["monitor_since"] == "2026-01-05"


def test_onboarding_status_accepts_older_monitoring_start(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session, email="monitoring-window@example.com")
    user.gmail_onboarding_skipped_at = datetime.now(timezone.utc)
    db_session.commit()
    authenticate_client(input_client, user=user)

    input_client.post(
        "/onboarding/canvas-ics",
        headers={"X-API-Key": "test-api-key"},
        json={"url": "https://example.com/expired.ics"},
    )
    monitoring_response = input_client.post(
        "/onboarding/monitoring-window",
        headers={"X-API-Key": "test-api-key"},
        json={"monitor_since": "2020-01-05"},
    )
    assert monitoring_response.status_code == 200
    assert monitoring_response.json()["stage"] == "ready"

    status_response = input_client.get("/onboarding/status", headers={"X-API-Key": "test-api-key"})
    assert status_response.status_code == 200
    assert status_response.json()["stage"] == "ready"
