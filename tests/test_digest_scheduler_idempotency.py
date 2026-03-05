from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.notify import DigestSendLog, Notification, NotificationChannel, NotificationStatus
from app.db.models.review import Change, ChangeType, Input, InputType, Snapshot
from app.db.models.shared import User
from app.modules.notify.digest_service import send_digest_for_slot


def test_send_digest_for_slot_is_idempotent(db_session: Session, monkeypatch) -> None:
    user = User(email="owner@example.com", notify_email="owner@example.com", calendar_delay_seconds=120)
    db_session.add(user)
    db_session.flush()

    input_row = Input(
        user_id=user.id,
        type=InputType.EMAIL,
        identity_key="digest-test-input",
        is_active=True,
    )
    db_session.add(input_row)
    db_session.flush()

    snapshot = Snapshot(
        input_id=input_row.id,
        content_hash="abc123",
        event_count=1,
        raw_evidence_key={"kind": "dev"},
    )
    db_session.add(snapshot)
    db_session.flush()

    change = Change(
        input_id=input_row.id,
        event_uid="event-1",
        change_type=ChangeType.CREATED,
        detected_at=datetime.now(timezone.utc),
        before_json=None,
        after_json={"title": "Assignment", "course_label": "CSE 151A"},
        delta_seconds=None,
        before_snapshot_id=None,
        after_snapshot_id=snapshot.id,
    )
    db_session.add(change)
    db_session.flush()

    notification = Notification(
        change_id=change.id,
        channel=NotificationChannel.EMAIL,
        status=NotificationStatus.PENDING,
        idempotency_key=f"digest:test:{change.id}",
        deliver_after=datetime.now(timezone.utc),
        enqueue_reason="digest_queue",
        sent_at=None,
        notified_at=None,
        error=None,
    )
    db_session.add(notification)
    db_session.commit()

    send_calls = {"count": 0}

    def fake_send(self, to_email: str, input_label: str, input_id: int, items):  # noqa: ANN001
        del to_email, input_label, input_id, items
        send_calls["count"] += 1

        class _Result:
            success = True
            error = None

        return _Result()

    monkeypatch.setattr("app.modules.notify.email.SMTPEmailNotifier.send_changes_digest", fake_send)

    now = datetime(2026, 2, 24, 17, 1, tzinfo=timezone.utc)
    send_digest_for_slot(
        db_session,
        user=user,
        scheduled_local_date=now.date(),
        scheduled_local_time="09:01",
        now=now,
    )
    send_digest_for_slot(
        db_session,
        user=user,
        scheduled_local_date=now.date(),
        scheduled_local_time="09:01",
        now=now,
    )

    db_session.expire_all()
    logs = db_session.scalars(select(DigestSendLog).where(DigestSendLog.user_id == user.id)).all()
    assert len(logs) == 1
    assert logs[0].status == "sent"
    assert send_calls["count"] == 1

    refreshed_notification = db_session.get(Notification, notification.id)
    assert refreshed_notification is not None
    assert refreshed_notification.notified_at is not None
    assert refreshed_notification.status == NotificationStatus.SENT
