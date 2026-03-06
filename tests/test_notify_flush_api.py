from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models.notify import DigestSendLog, Notification, NotificationStatus
from app.db.models.review import Change, ChangeType, Input, InputType
from app.db.models.shared import User
from app.modules.core_ingest.pending_review_outbox import emit_review_pending_created_event


def _seed_pending_notification_outbox(db_session) -> tuple[User, Input, Change]:
    now = datetime.now(timezone.utc)
    user = User(
        email="notify-owner@example.com",
        notify_email="notify-owner@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    input_row = Input(
        user_id=user.id,
        type=InputType.EMAIL,
        identity_key=f"canonical:user:{user.id}",
        is_active=True,
    )
    db_session.add(input_row)
    db_session.flush()

    change = Change(
        input_id=input_row.id,
        event_uid="notify-flush-evt-1",
        change_type=ChangeType.CREATED,
        detected_at=now,
        before_json=None,
        after_json={"title": "Quiz 1", "course_label": "CSE 151A"},
        delta_seconds=None,
        proposal_merge_key="notify-flush-evt-1",
        proposal_sources_json=[],
    )
    db_session.add(change)
    db_session.flush()

    emit_review_pending_created_event(
        db=db_session,
        canonical_input_id=input_row.id,
        changes=[change],
        detected_at=now,
    )
    db_session.commit()
    return user, input_row, change


def test_notification_flush_endpoint_enqueues_and_sends(monkeypatch, db_engine, db_session, tmp_path: Path) -> None:
    del db_engine
    sink_path = tmp_path / "notify_flush.jsonl"
    monkeypatch.setenv("NOTIFY_SINK_MODE", "jsonl")
    monkeypatch.setenv("NOTIFY_JSONL_PATH", str(sink_path))
    get_settings.cache_clear()

    _seed_pending_notification_outbox(db_session)
    from services.notification_api.main import app as notification_app

    headers = {"X-Service-Name": "ops", "X-Service-Token": "test-internal-token-ops"}
    with TestClient(notification_app) as client:
        response = client.post(
            "/internal/notifications/flush",
            headers=headers,
            json={"run_id": "semester-demo-run", "semester": 1, "batch": 3, "force_due": True},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enqueued_notifications"] >= 1
    assert payload["processed_slots"] >= 1
    assert payload["sent_count"] >= 1
    assert payload["failed_count"] == 0

    notification_row = db_session.scalar(select(Notification).where(Notification.status == NotificationStatus.SENT))
    assert notification_row is not None
    digest_log = db_session.scalar(select(DigestSendLog).where(DigestSendLog.status == "sent"))
    assert digest_log is not None

    assert sink_path.is_file()
    row = json.loads(sink_path.read_text(encoding="utf-8").splitlines()[0])
    assert row["run_id"] == "semester-demo-run"
    assert row["semester"] == 1
    assert row["batch"] == 3
    get_settings.cache_clear()


def test_notification_flush_endpoint_handles_empty_state(monkeypatch, db_engine, tmp_path: Path) -> None:
    del db_engine
    sink_path = tmp_path / "notify_flush_empty.jsonl"
    monkeypatch.setenv("NOTIFY_SINK_MODE", "jsonl")
    monkeypatch.setenv("NOTIFY_JSONL_PATH", str(sink_path))
    get_settings.cache_clear()
    from services.notification_api.main import app as notification_app

    headers = {"X-Service-Name": "ops", "X-Service-Token": "test-internal-token-ops"}
    with TestClient(notification_app) as client:
        response = client.post(
            "/internal/notifications/flush",
            headers=headers,
            json={"run_id": "empty-run", "semester": 1, "batch": 0, "force_due": True},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enqueued_notifications"] == 0
    assert payload["processed_slots"] == 0
    assert payload["sent_count"] == 0
    assert payload["failed_count"] == 0
    assert not sink_path.exists()
    get_settings.cache_clear()
