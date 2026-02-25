from __future__ import annotations

import threading
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Change, ChangeType, Notification, NotificationStatus, Snapshot, Input, InputType, User
from app.modules.notify.email import SMTPEmailNotifier
from app.modules.notify.interface import ChangeDigestItem, SendResult
from app.modules.notify.service import dispatch_notifications_for_changes


class StubNotifier:
    def __init__(self, success: bool) -> None:
        self.success = success
        self.calls: list[tuple[str, str, int, list[ChangeDigestItem]]] = []

    def send_changes_digest(
        self,
        to_email: str,
        source_name: str,
        source_id: int,
        items: list[ChangeDigestItem],
    ) -> SendResult:
        self.calls.append((to_email, source_name, source_id, items))
        if self.success:
            return SendResult(success=True)
        return SendResult(success=False, error="smtp down")


def test_notification_rows_marked_sent_on_success(db_session: Session) -> None:
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Input(
        user_id=user.id,
        type=InputType.ICS,
        name="Course Deadlines",
        normalized_name="course deadlines",
        encrypted_url="encrypted",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(source)
    db_session.flush()

    snapshot = Snapshot(
        input_id=source.id,
        content_hash="abc123",
        event_count=1,
        raw_evidence_key={"kind": "ics", "store": "fs", "path": "evidence/ics/source_1/file.ics"},
    )
    db_session.add(snapshot)
    db_session.flush()

    change = Change(
        input_id=source.id,
        event_uid="uid-1",
        change_type=ChangeType.DUE_CHANGED,
        detected_at=datetime.now(timezone.utc),
        before_json={"title": "A", "start_at_utc": "2026-02-20T10:00:00+00:00", "course_label": "CSE 151A"},
        after_json={"title": "A", "start_at_utc": "2026-02-20T11:00:00+00:00", "course_label": "CSE 151A"},
        delta_seconds=3600,
        after_snapshot_id=snapshot.id,
    )
    db_session.add(change)
    db_session.flush()

    notifier = StubNotifier(success=True)
    result = dispatch_notifications_for_changes(db_session, source, [change], notifier=notifier)
    db_session.commit()

    assert result.email_sent is True
    assert result.error is None
    assert len(notifier.calls) == 1

    rows = db_session.scalars(select(Notification)).all()
    assert len(rows) == 1
    assert rows[0].status == NotificationStatus.SENT
    assert rows[0].sent_at is not None
    assert rows[0].idempotency_key == f"email:change:{change.id}"


def test_notification_rows_marked_failed_on_error(db_session: Session) -> None:
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Input(
        user_id=user.id,
        type=InputType.ICS,
        name="Course Deadlines",
        normalized_name="course deadlines",
        encrypted_url="encrypted",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(source)
    db_session.flush()

    snapshot = Snapshot(
        input_id=source.id,
        content_hash="abc123",
        event_count=1,
        raw_evidence_key={"kind": "ics", "store": "fs", "path": "evidence/ics/source_1/file.ics"},
    )
    db_session.add(snapshot)
    db_session.flush()

    change = Change(
        input_id=source.id,
        event_uid="uid-1",
        change_type=ChangeType.TITLE_CHANGED,
        detected_at=datetime.now(timezone.utc),
        before_json={"title": "Old", "course_label": "Unknown"},
        after_json={"title": "New", "course_label": "Unknown"},
        delta_seconds=None,
        after_snapshot_id=snapshot.id,
    )
    db_session.add(change)
    db_session.flush()

    notifier = StubNotifier(success=False)
    result = dispatch_notifications_for_changes(db_session, source, [change], notifier=notifier)
    db_session.commit()

    assert result.email_sent is False
    assert result.error == "smtp down"

    rows = db_session.scalars(select(Notification)).all()
    assert len(rows) == 1
    assert rows[0].status == NotificationStatus.FAILED
    assert rows[0].error == "smtp down"
    assert rows[0].idempotency_key == f"email:change:{change.id}"


def test_notification_dispatch_is_idempotent_for_same_change(db_session: Session) -> None:
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Input(
        user_id=user.id,
        type=InputType.ICS,
        name="Course Deadlines",
        normalized_name="course deadlines",
        encrypted_url="encrypted",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(source)
    db_session.flush()

    snapshot = Snapshot(
        input_id=source.id,
        content_hash="abc123",
        event_count=1,
        raw_evidence_key={"kind": "ics", "store": "fs", "path": "evidence/ics/source_1/file.ics"},
    )
    db_session.add(snapshot)
    db_session.flush()

    change = Change(
        input_id=source.id,
        event_uid="uid-1",
        change_type=ChangeType.TITLE_CHANGED,
        detected_at=datetime.now(timezone.utc),
        before_json={"title": "Old", "course_label": "Unknown"},
        after_json={"title": "New", "course_label": "Unknown"},
        delta_seconds=None,
        after_snapshot_id=snapshot.id,
    )
    db_session.add(change)
    db_session.flush()

    notifier = StubNotifier(success=True)
    first = dispatch_notifications_for_changes(db_session, source, [change], notifier=notifier)
    second = dispatch_notifications_for_changes(db_session, source, [change], notifier=notifier)
    db_session.commit()

    assert first.email_sent is True
    assert second.email_sent is False
    assert len(notifier.calls) == 1

    rows = db_session.scalars(select(Notification).where(Notification.change_id == change.id)).all()
    assert len(rows) == 1
    assert rows[0].status == NotificationStatus.SENT
    assert rows[0].idempotency_key == f"email:change:{change.id}"


def test_failed_notification_is_not_retried_automatically(db_session: Session) -> None:
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Input(
        user_id=user.id,
        type=InputType.ICS,
        name="Course Deadlines",
        normalized_name="course deadlines",
        encrypted_url="encrypted",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(source)
    db_session.flush()

    snapshot = Snapshot(
        input_id=source.id,
        content_hash="abc123",
        event_count=1,
        raw_evidence_key={"kind": "ics", "store": "fs", "path": "evidence/ics/source_1/file.ics"},
    )
    db_session.add(snapshot)
    db_session.flush()

    change = Change(
        input_id=source.id,
        event_uid="uid-1",
        change_type=ChangeType.TITLE_CHANGED,
        detected_at=datetime.now(timezone.utc),
        before_json={"title": "Old", "course_label": "Unknown"},
        after_json={"title": "New", "course_label": "Unknown"},
        delta_seconds=None,
        after_snapshot_id=snapshot.id,
    )
    db_session.add(change)
    db_session.flush()

    failed_notifier = StubNotifier(success=False)
    first = dispatch_notifications_for_changes(db_session, source, [change], notifier=failed_notifier)
    db_session.commit()

    assert first.email_sent is False
    assert first.error == "smtp down"
    assert len(failed_notifier.calls) == 1

    success_notifier = StubNotifier(success=True)
    second = dispatch_notifications_for_changes(db_session, source, [change], notifier=success_notifier)
    db_session.commit()

    assert second.email_sent is False
    assert second.error is None
    assert second.dedup_skipped_count == 1
    assert len(success_notifier.calls) == 0

    rows = db_session.scalars(select(Notification).where(Notification.change_id == change.id)).all()
    assert len(rows) == 1
    assert rows[0].status == NotificationStatus.FAILED


def test_notification_insert_race_results_in_single_row_and_single_send(db_session, db_session_factory) -> None:
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Input(
        user_id=user.id,
        type=InputType.ICS,
        name="Race Input",
        normalized_name="race source",
        encrypted_url="encrypted",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(source)
    db_session.flush()

    snapshot = Snapshot(
        input_id=source.id,
        content_hash="abc123",
        event_count=1,
        raw_evidence_key={"kind": "ics", "store": "fs", "path": "evidence/ics/source_race/file.ics"},
    )
    db_session.add(snapshot)
    db_session.flush()

    change = Change(
        input_id=source.id,
        event_uid="uid-race",
        change_type=ChangeType.CREATED,
        detected_at=datetime.now(timezone.utc),
        before_json=None,
        after_json={"title": "New Item", "course_label": "CSE 151A"},
        delta_seconds=None,
        after_snapshot_id=snapshot.id,
    )
    db_session.add(change)
    db_session.commit()

    call_count = 0
    call_lock = threading.Lock()
    start_barrier = threading.Barrier(2)
    errors: list[str] = []

    class ThreadSafeNotifier:
        def send_changes_digest(self, to_email: str, source_name: str, source_id: int, items: list[ChangeDigestItem]) -> SendResult:
            del to_email, source_name, source_id, items
            nonlocal call_count
            with call_lock:
                call_count += 1
            return SendResult(success=True)

    def worker() -> None:
        try:
            session = db_session_factory()
            try:
                source_row = session.get(Input, source.id)
                change_row = session.get(Change, change.id)
                assert source_row is not None
                assert change_row is not None
                start_barrier.wait()
                dispatch_notifications_for_changes(session, source_row, [change_row], notifier=ThreadSafeNotifier())
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
    assert call_count == 1

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
                evidence_path="evidence/ics/source_123/sample.ics",
            )
        ],
    )

    assert result.success is True
    assert sent["host"] == "smtp.test"
    assert sent["port"] == 2525
    assert "Deadline Diff" in str(sent["subject"])
    assert sent["to"] == "user@test.local"
    get_settings.cache_clear()
