from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Notification, User


def test_dev_inject_notify_respects_gate(client, monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ENABLE_DEV_ENDPOINTS", "false")
    get_settings.cache_clear()

    response = client.post(
        "/v1/dev/inject_notify",
        headers={"X-API-Key": "test-api-key"},
        json={
            "subject": "demo",
            "from": "demo@example.com",
            "date": "2026-02-24T10:00:00Z",
            "body_text": "hello",
        },
    )
    assert response.status_code == 404


def test_dev_inject_notify_requires_initialized_user(client, monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ENABLE_DEV_ENDPOINTS", "true")
    get_settings.cache_clear()

    response = client.post(
        "/v1/dev/inject_notify",
        headers={"X-API-Key": "test-api-key"},
        json={
            "subject": "demo",
            "from": "demo@example.com",
            "date": "2026-02-24T10:00:00Z",
            "body_text": "hello",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "user_not_initialized"


def test_dev_inject_notify_creates_digest_eligible_row(client, db_session, monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ENABLE_DEV_ENDPOINTS", "true")
    get_settings.cache_clear()
    user = User(
        email=None,
        notify_email="student@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()

    response = client.post(
        "/v1/dev/inject_notify",
        headers={"X-API-Key": "test-api-key"},
        json={
            "subject": "Homework deadline moved",
            "from": "staff@example.edu",
            "date": "2026-02-24T10:00:00Z",
            "body_text": "Deadline moved to Sunday",
            "event_type": "deadline",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ui_path"].startswith("/ui/feed")

    notification = db_session.scalar(select(Notification).where(Notification.id == payload["notification_id"]))
    assert notification is not None
    assert notification.enqueue_reason == "digest_queue"
    assert notification.notified_at is None
