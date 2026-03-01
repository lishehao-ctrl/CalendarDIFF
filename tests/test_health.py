from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import InputSource, SourceKind, User


def test_health_returns_scheduler_summary(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()

    assert "db" in payload
    assert "scheduler" in payload
    assert "running" in payload["scheduler"]
    assert "last_run_started_at" in payload["scheduler"]
    assert "last_run_success_count" in payload["scheduler"]
    assert "last_run_failed_count" in payload["scheduler"]
    assert "last_run_notification_failed_count" in payload["scheduler"]
    assert "cumulative_success_count" in payload["scheduler"]
    assert "cumulative_failed_count" in payload["scheduler"]
    assert "cumulative_notification_failed_count" in payload["scheduler"]
    assert "cumulative_run_executed_count" in payload["scheduler"]
    assert "cumulative_run_skipped_lock_count" in payload["scheduler"]
    assert "next_expected_check_at" in payload["scheduler"]
    assert "next_expected_source_id" in payload["scheduler"]
    assert "lock_backend" in payload["scheduler"]
    assert "database_dialect" in payload["scheduler"]


def test_health_reports_global_next_expected_check(client, db_session) -> None:
    early_user = User(email="owner-early@example.com")
    late_user = User(email="owner-late@example.com")
    db_session.add_all([early_user, late_user])
    db_session.flush()

    source_early = InputSource(
        user_id=early_user.id,
        source_kind=SourceKind.CALENDAR,
        provider="calendar",
        source_key="health-test-early",
        poll_interval_seconds=900,
        is_active=True,
        last_polled_at=datetime(2026, 2, 21, 10, 0, tzinfo=timezone.utc),
        next_poll_at=datetime(2026, 2, 21, 10, 15, tzinfo=timezone.utc),
    )
    source_late = InputSource(
        user_id=late_user.id,
        source_kind=SourceKind.CALENDAR,
        provider="calendar",
        source_key="health-test-late",
        poll_interval_seconds=900,
        is_active=True,
        last_polled_at=datetime(2026, 2, 21, 10, 30, tzinfo=timezone.utc),
        next_poll_at=datetime(2026, 2, 21, 10, 45, tzinfo=timezone.utc),
    )
    db_session.add_all([source_early, source_late])
    db_session.commit()

    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()

    scheduler = payload["scheduler"]
    assert scheduler["next_expected_source_id"] == source_early.id
    next_expected = datetime.fromisoformat(scheduler["next_expected_check_at"].replace("Z", "+00:00"))
    assert next_expected == datetime(2026, 2, 21, 10, 15, tzinfo=timezone.utc)
