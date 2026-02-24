from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import (
    Change,
    ChangeType,
    Notification,
    NotificationChannel,
    NotificationStatus,
    Snapshot,
    Source,
    SourceType,
    User,
    UserTerm,
)


def _parse_utc(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def test_changes_feed_orders_email_before_calendar_and_exposes_notification_state(client, db_session) -> None:
    now = datetime.now(timezone.utc)

    user = User(
        email="owner@example.com",
        notify_email="student-a@example.com",
        calendar_delay_seconds=120,
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()
    user_term = UserTerm(
        user_id=user.id,
        code="WI26",
        label="Winter 2026",
        starts_on=datetime(2026, 1, 1, tzinfo=timezone.utc).date(),
        ends_on=datetime(2026, 12, 31, tzinfo=timezone.utc).date(),
        is_active=True,
    )
    db_session.add(user_term)
    db_session.flush()

    ics_source = Source(
        user_id=user.id,
        type=SourceType.ICS,
        identity_key="calendar-input-a",
        encrypted_url="encrypted-ics",
        interval_minutes=15,
        is_active=True,
    )
    email_source = Source(
        user_id=user.id,
        type=SourceType.EMAIL,
        provider="gmail",
        gmail_account_email="student-a@school.edu",
        identity_key="email-input-a",
        encrypted_url="encrypted-email",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add_all([ics_source, email_source])
    db_session.flush()

    ics_before_snapshot = Snapshot(
        input_id=ics_source.id,
        retrieved_at=now - timedelta(minutes=10),
        etag="ics-before",
        content_hash="ics-before-snapshot-hash",
        event_count=1,
        raw_evidence_key={"kind": "ics"},
    )
    ics_after_snapshot = Snapshot(
        input_id=ics_source.id,
        retrieved_at=now,
        etag="ics-after",
        content_hash="ics-after-snapshot-hash",
        event_count=1,
        raw_evidence_key={"kind": "ics"},
    )
    email_snapshot = Snapshot(
        input_id=email_source.id,
        retrieved_at=now,
        etag=None,
        content_hash="email-snapshot-hash",
        event_count=1,
        raw_evidence_key={"kind": "gmail"},
    )
    db_session.add_all([ics_before_snapshot, ics_after_snapshot, email_snapshot])
    db_session.flush()

    calendar_change = Change(
        input_id=ics_source.id,
        user_term_id=user_term.id,
        event_uid="calendar-change-1",
        change_type=ChangeType.DUE_CHANGED,
        detected_at=now,
        before_json={"title": "HW1", "start_at_utc": "2026-03-02T18:00:00+00:00"},
        after_json={"title": "HW1", "course_label": "CSE 151A", "start_at_utc": "2026-03-02T20:00:00+00:00"},
        delta_seconds=1200,
        before_snapshot_id=ics_before_snapshot.id,
        after_snapshot_id=ics_after_snapshot.id,
        evidence_keys={"after": {"kind": "ics"}},
    )
    email_change = Change(
        input_id=email_source.id,
        event_uid="gmail-message-1",
        change_type=ChangeType.CREATED,
        detected_at=now - timedelta(minutes=1),
        before_json=None,
        after_json={
            "subject": "Urgent update",
            "snippet": "Classroom changed",
            "gmail_message_id": "gmail-message-1",
            "internal_date": "2026-03-01T15:30:00+00:00",
        },
        delta_seconds=None,
        before_snapshot_id=None,
        after_snapshot_id=email_snapshot.id,
        evidence_keys={"after": {"kind": "gmail"}},
    )
    db_session.add_all([calendar_change, email_change])
    db_session.flush()

    db_session.add_all(
        [
            Notification(
                change_id=email_change.id,
                channel=NotificationChannel.EMAIL,
                status=NotificationStatus.SENT,
                sent_at=now,
                error=None,
                idempotency_key=f"email:change:{email_change.id}",
                deliver_after=now,
                enqueue_reason=None,
            ),
            Notification(
                change_id=calendar_change.id,
                channel=NotificationChannel.EMAIL,
                status=NotificationStatus.PENDING,
                sent_at=None,
                error=None,
                idempotency_key=f"email:change:{calendar_change.id}",
                deliver_after=now + timedelta(seconds=120),
                enqueue_reason="email_priority_delay",
            ),
        ]
    )
    db_session.commit()

    headers = {"X-API-Key": "test-api-key"}
    response = client.get("/v1/feed?limit=20", headers=headers)
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2

    assert rows[0]["input_type"] == "email"
    assert rows[0]["priority_rank"] == 0
    assert rows[0]["priority_label"] == "high"
    assert rows[0]["notification_state"] == "sent"
    assert "user_id" not in rows[0]
    assert "user_notify_email" not in rows[0]
    assert rows[0]["change_summary"]["old"]["value_time"] is None
    assert rows[0]["change_summary"]["old"]["source_observed_at"] is None
    assert _parse_utc(rows[0]["change_summary"]["new"]["value_time"]) == datetime(2026, 3, 1, 15, 30, tzinfo=timezone.utc)
    assert rows[0]["change_summary"]["new"]["source_type"] == "email"
    assert rows[0]["change_summary"]["new"]["source_label"] == "Gmail · student-a@school.edu"
    assert _parse_utc(rows[0]["change_summary"]["new"]["source_observed_at"]) == email_snapshot.retrieved_at

    assert rows[1]["input_type"] == "ics"
    assert rows[1]["priority_rank"] == 1
    assert rows[1]["priority_label"] == "normal"
    assert rows[1]["notification_state"] == "queued_delayed_by_email_priority"
    assert rows[1]["deliver_after"] is not None
    assert "user_id" not in rows[1]
    assert "user_notify_email" not in rows[1]
    assert _parse_utc(rows[1]["change_summary"]["old"]["value_time"]) == datetime(2026, 3, 2, 18, 0, tzinfo=timezone.utc)
    assert _parse_utc(rows[1]["change_summary"]["new"]["value_time"]) == datetime(2026, 3, 2, 20, 0, tzinfo=timezone.utc)
    assert rows[1]["change_summary"]["old"]["source_type"] == "ics"
    assert rows[1]["change_summary"]["new"]["source_type"] == "ics"
    assert rows[1]["change_summary"]["old"]["source_label"] == ics_source.display_label
    assert rows[1]["change_summary"]["new"]["source_label"] == ics_source.display_label
    assert _parse_utc(rows[1]["change_summary"]["old"]["source_observed_at"]) == ics_before_snapshot.retrieved_at
    assert _parse_utc(rows[1]["change_summary"]["new"]["source_observed_at"]) == ics_after_snapshot.retrieved_at


def test_changes_feed_source_type_filter(client, db_session) -> None:
    user = User(email="owner@example.com", notify_email="student-a@example.com", onboarding_completed_at=datetime.now(timezone.utc))
    db_session.add(user)
    db_session.flush()
    user_term = UserTerm(
        user_id=user.id,
        code="WI26",
        label="Winter 2026",
        starts_on=datetime(2026, 1, 1, tzinfo=timezone.utc).date(),
        ends_on=datetime(2026, 12, 31, tzinfo=timezone.utc).date(),
        is_active=True,
    )
    db_session.add(user_term)
    db_session.flush()

    ics_source = Source(
        user_id=user.id,
        type=SourceType.ICS,
        identity_key="calendar-input-b",
        encrypted_url="encrypted-ics",
        interval_minutes=15,
        is_active=True,
    )
    email_source = Source(
        user_id=user.id,
        type=SourceType.EMAIL,
        provider="gmail",
        identity_key="email-input-b",
        encrypted_url="encrypted-email",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add_all([ics_source, email_source])
    db_session.flush()

    now = datetime.now(timezone.utc)
    ics_snapshot = Snapshot(
        input_id=ics_source.id,
        retrieved_at=now,
        etag=None,
        content_hash="ics-hash",
        event_count=1,
        raw_evidence_key={"kind": "ics"},
    )
    email_snapshot = Snapshot(
        input_id=email_source.id,
        retrieved_at=now,
        etag=None,
        content_hash="email-hash",
        event_count=1,
        raw_evidence_key={"kind": "gmail"},
    )
    db_session.add_all([ics_snapshot, email_snapshot])
    db_session.flush()

    db_session.add_all(
        [
            Change(
                input_id=ics_source.id,
                user_term_id=user_term.id,
                event_uid="ics-1",
                change_type=ChangeType.DUE_CHANGED,
                detected_at=now,
                before_json={"title": "HW2"},
                after_json={"title": "HW2 updated"},
                delta_seconds=300,
                before_snapshot_id=None,
                after_snapshot_id=ics_snapshot.id,
                evidence_keys={"after": {"kind": "ics"}},
            ),
            Change(
                input_id=email_source.id,
                event_uid="gmail-1",
                change_type=ChangeType.CREATED,
                detected_at=now,
                before_json=None,
                after_json={"subject": "Reminder"},
                delta_seconds=None,
                before_snapshot_id=None,
                after_snapshot_id=email_snapshot.id,
                evidence_keys={"after": {"kind": "gmail"}},
            ),
        ]
    )
    db_session.commit()

    headers = {"X-API-Key": "test-api-key"}
    response = client.get("/v1/feed?input_types=ics", headers=headers)
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["input_type"] == "ics"
    assert rows[0]["change_summary"]["old"]["value_time"] is None
    assert rows[0]["change_summary"]["new"]["value_time"] is None


def test_changes_feed_current_scope_falls_back_to_all_when_no_active_term(client, db_session) -> None:
    now = datetime.now(timezone.utc)
    user = User(
        email="owner@example.com",
        notify_email="student-a@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    ics_source = Source(
        user_id=user.id,
        type=SourceType.ICS,
        identity_key="calendar-input-current-fallback",
        encrypted_url="encrypted-ics",
        interval_minutes=15,
        is_active=True,
    )
    email_source = Source(
        user_id=user.id,
        type=SourceType.EMAIL,
        provider="gmail",
        identity_key="email-input-current-fallback",
        encrypted_url="encrypted-email",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add_all([ics_source, email_source])
    db_session.flush()

    ics_snapshot = Snapshot(
        input_id=ics_source.id,
        retrieved_at=now,
        etag=None,
        content_hash="ics-current-fallback-hash",
        event_count=1,
        raw_evidence_key={"kind": "ics"},
    )
    email_snapshot = Snapshot(
        input_id=email_source.id,
        retrieved_at=now,
        etag=None,
        content_hash="email-current-fallback-hash",
        event_count=1,
        raw_evidence_key={"kind": "gmail"},
    )
    db_session.add_all([ics_snapshot, email_snapshot])
    db_session.flush()

    db_session.add_all(
        [
            Change(
                input_id=ics_source.id,
                user_term_id=None,
                event_uid="ics-current-fallback",
                change_type=ChangeType.DUE_CHANGED,
                detected_at=now,
                before_json={"title": "HW1"},
                after_json={"title": "HW1 updated"},
                delta_seconds=600,
                before_snapshot_id=None,
                after_snapshot_id=ics_snapshot.id,
                evidence_keys={"after": {"kind": "ics"}},
            ),
            Change(
                input_id=email_source.id,
                user_term_id=None,
                event_uid="email-current-fallback",
                change_type=ChangeType.CREATED,
                detected_at=now - timedelta(minutes=1),
                before_json=None,
                after_json={"subject": "Reminder"},
                delta_seconds=None,
                before_snapshot_id=None,
                after_snapshot_id=email_snapshot.id,
                evidence_keys={"after": {"kind": "gmail"}},
            ),
        ]
    )
    db_session.commit()

    response = client.get("/v1/feed?term_scope=current", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert sorted(row["input_type"] for row in rows) == ["email", "ics"]
