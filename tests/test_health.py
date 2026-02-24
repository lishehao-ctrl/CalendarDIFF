from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import Source, SourceType, User


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
    assert "next_expected_input_id" in payload["scheduler"]
    assert "lock_backend" in payload["scheduler"]
    assert "database_dialect" in payload["scheduler"]


def test_health_reports_global_next_expected_check(client, db_session) -> None:
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source_early = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name="Source Early",
        normalized_name="source early",
        encrypted_url="encrypted-1",
        interval_minutes=15,
        is_active=True,
        last_checked_at=datetime(2026, 2, 21, 10, 0, tzinfo=timezone.utc),
    )
    source_late = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name="Source Late",
        normalized_name="source late",
        encrypted_url="encrypted-2",
        interval_minutes=15,
        is_active=True,
        last_checked_at=datetime(2026, 2, 21, 10, 30, tzinfo=timezone.utc),
    )
    db_session.add_all([source_early, source_late])
    db_session.commit()

    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()

    scheduler = payload["scheduler"]
    assert scheduler["next_expected_input_id"] == source_early.id
    next_expected = datetime.fromisoformat(scheduler["next_expected_check_at"].replace("Z", "+00:00"))
    assert next_expected == datetime(2026, 2, 21, 10, 15, tzinfo=timezone.utc)
