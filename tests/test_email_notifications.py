from __future__ import annotations

import threading
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.notify import Notification, NotificationStatus
from app.db.models.review import Change, ChangeType, Input, InputType, Snapshot
from app.db.models.shared import User
from app.modules.notify.email import SMTPEmailNotifier
from app.modules.notify.interface import ChangeDigestItem, SendResult
from app.modules.notify.service import enqueue_notifications_for_changes


def _build_change(db_session: Session, *, change_type: ChangeType) -> tuple[Input, Change]:
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    input_row = Input(
        user_id=user.id,
        type=InputType.ICS,
        identity_key="Course Deadlines",
        is_active=True,
    )
    db_session.add(input_row)
    db_session.flush()

    snapshot = Snapshot(
        input_id=input_row.id,
        content_hash="abc123",
        event_count=1,
        raw_evidence_key={"kind": "ics", "store": "fs", "path": "evidence/ics/input_1/file.ics"},
    )
    db_session.add(snapshot)
    db_session.flush()

    change = Change(
        input_id=input_row.id,
        event_uid="uid-1",
        change_type=change_type,
        detected_at=datetime.now(timezone.utc),
        before_json={"title": "Old", "course_label": "CSE 151A"},
        after_json={"title": "New", "course_label": "CSE 151A"},
        delta_seconds=3600 if change_type == ChangeType.DUE_CHANGED else None,
        after_snapshot_id=snapshot.id,
    )
    db_session.add(change)
    db_session.flush()
    return input_row, change


def test_enqueue_notifications_creates_pending_row(db_session: Session) -> None:
    input_row, change = _build_change(db_session, change_type=ChangeType.DUE_CHANGED)

    result = enqueue_notifications_for_changes(
        db_session,
        input_row,
        [change],
        deliver_after=datetime.now(timezone.utc),
        enqueue_reason="digest_queue",
    )
    db_session.commit()

    assert result.enqueued_count == 1
    assert result.dedup_skipped_count == 0
    assert result.notification_state == "queued"

    rows = db_session.scalars(select(Notification).where(Notification.change_id == change.id)).all()
    assert len(rows) == 1
    assert rows[0].status == NotificationStatus.PENDING
    assert rows[0].enqueue_reason == "digest_queue"
    assert rows[0].idempotency_key == f"email:change:{change.id}"


def test_enqueue_notifications_is_idempotent_for_same_change(db_session: Session) -> None:
    input_row, change = _build_change(db_session, change_type=ChangeType.CREATED)

    first = enqueue_notifications_for_changes(
        db_session,
        input_row,
        [change],
        deliver_after=datetime.now(timezone.utc),
        enqueue_reason="digest_queue",
    )
    second = enqueue_notifications_for_changes(
        db_session,
        input_row,
        [change],
        deliver_after=datetime.now(timezone.utc),
        enqueue_reason="digest_queue",
    )
    db_session.commit()

    assert first.enqueued_count == 1
    assert second.enqueued_count == 0
    assert second.dedup_skipped_count == 1

    rows = db_session.scalars(select(Notification).where(Notification.change_id == change.id)).all()
    assert len(rows) == 1
    assert rows[0].status == NotificationStatus.PENDING


def test_enqueue_notification_insert_race_results_in_single_row(db_session, db_session_factory) -> None:
    input_row, change = _build_change(db_session, change_type=ChangeType.CREATED)
    db_session.commit()

    start_barrier = threading.Barrier(2)
    errors: list[str] = []

    def worker() -> None:
        try:
            session = db_session_factory()
            try:
                input_db = session.get(Input, input_row.id)
                change_db = session.get(Change, change.id)
                assert input_db is not None
                assert change_db is not None
                start_barrier.wait()
                enqueue_notifications_for_changes(
                    session,
                    input_db,
                    [change_db],
                    deliver_after=datetime.now(timezone.utc),
                    enqueue_reason="digest_queue",
                )
                session.commit()
            finally:
                session.close()
        except Exception as exc:  # pragma: no cover - defensive branch
            errors.append(str(exc))

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert errors == []
    db_session.expire_all()
    rows = db_session.scalars(select(Notification).where(Notification.change_id == change.id)).all()
    assert len(rows) == 1


def test_smtp_notifier_uses_smtp_transport(monkeypatch) -> None:
    sent: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            sent["host"] = host
            sent["port"] = port
            sent["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self) -> None:
            sent["starttls"] = True

        def login(self, username: str, password: str) -> None:
            sent["login"] = (username, password)

        def send_message(self, message) -> None:
            sent["subject"] = message["Subject"]
            sent["to"] = message["To"]

    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "no-reply@test.local")
    get_settings.cache_clear()
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)

    notifier = SMTPEmailNotifier()
    result = notifier.send_changes_digest(
        to_email="user@test.local",
        input_label="Input A",
        input_id=123,
        items=[
            ChangeDigestItem(
                event_uid="u1",
                change_type="due_changed",
                course_label="CSE 151A",
                title="Homework 1",
                before_start_at_utc="2026-02-21T12:00:00+00:00",
                after_start_at_utc="2026-02-21T13:00:00+00:00",
                delta_seconds=3600,
                detected_at=datetime.now(timezone.utc),
                evidence_path="evidence/ics/input_123/sample.ics",
            )
        ],
    )

    assert isinstance(result, SendResult)
    assert result.success is True
    assert sent["host"] == "smtp.test"
    assert sent["port"] == 2525
    assert "Deadline Diff" in str(sent["subject"])
    assert sent["to"] == "user@test.local"
    get_settings.cache_clear()
