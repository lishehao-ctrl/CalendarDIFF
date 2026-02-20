from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import Change, ChangeType, Notification, NotificationStatus, Snapshot, Source, SourceType, User
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


def test_notification_rows_marked_sent_on_success() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        user = User(email="owner@example.com")
        db.add(user)
        db.flush()

        source = Source(
            user_id=user.id,
            type=SourceType.ICS,
            name="Course Deadlines",
            encrypted_url="encrypted",
            interval_minutes=15,
            is_active=True,
        )
        db.add(source)
        db.flush()

        snapshot = Snapshot(
            source_id=source.id,
            content_hash="abc123",
            event_count=1,
            raw_evidence_key={"kind": "ics", "store": "fs", "path": "evidence/ics/source_1/file.ics"},
        )
        db.add(snapshot)
        db.flush()

        change = Change(
            source_id=source.id,
            event_uid="uid-1",
            change_type=ChangeType.DUE_CHANGED,
            detected_at=datetime.now(timezone.utc),
            before_json={"title": "A", "start_at_utc": "2026-02-20T10:00:00+00:00", "course_label": "CSE 151A"},
            after_json={"title": "A", "start_at_utc": "2026-02-20T11:00:00+00:00", "course_label": "CSE 151A"},
            delta_seconds=3600,
            after_snapshot_id=snapshot.id,
        )
        db.add(change)
        db.flush()

        notifier = StubNotifier(success=True)
        result = dispatch_notifications_for_changes(db, source, [change], notifier=notifier)
        db.commit()

        assert result.email_sent is True
        assert result.error is None
        assert len(notifier.calls) == 1

        rows = db.scalars(select(Notification)).all()
        assert len(rows) == 1
        assert rows[0].status == NotificationStatus.SENT
        assert rows[0].sent_at is not None


def test_notification_rows_marked_failed_on_error() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        user = User(email="owner@example.com")
        db.add(user)
        db.flush()

        source = Source(
            user_id=user.id,
            type=SourceType.ICS,
            name="Course Deadlines",
            encrypted_url="encrypted",
            interval_minutes=15,
            is_active=True,
        )
        db.add(source)
        db.flush()

        snapshot = Snapshot(
            source_id=source.id,
            content_hash="abc123",
            event_count=1,
            raw_evidence_key={"kind": "ics", "store": "fs", "path": "evidence/ics/source_1/file.ics"},
        )
        db.add(snapshot)
        db.flush()

        change = Change(
            source_id=source.id,
            event_uid="uid-1",
            change_type=ChangeType.TITLE_CHANGED,
            detected_at=datetime.now(timezone.utc),
            before_json={"title": "Old", "course_label": "Unknown"},
            after_json={"title": "New", "course_label": "Unknown"},
            delta_seconds=None,
            after_snapshot_id=snapshot.id,
        )
        db.add(change)
        db.flush()

        notifier = StubNotifier(success=False)
        result = dispatch_notifications_for_changes(db, source, [change], notifier=notifier)
        db.commit()

        assert result.email_sent is False
        assert result.error == "smtp down"

        rows = db.scalars(select(Notification)).all()
        assert len(rows) == 1
        assert rows[0].status == NotificationStatus.FAILED
        assert rows[0].error == "smtp down"


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
        source_name="Source A",
        source_id=123,
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
            )
        ],
    )

    assert result.success is True
    assert sent["host"] == "smtp.test"
    assert sent["port"] == 2525
    assert "Deadline Diff" in str(sent["subject"])
    assert sent["to"] == "user@test.local"
    get_settings.cache_clear()
