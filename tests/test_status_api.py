from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import Input, InputType, SyncRun, SyncRunStatus, SyncTriggerType, User


def test_status_api_requires_api_key(client) -> None:
    response = client.get("/v1/status")
    assert response.status_code == 401


def test_status_api_returns_scheduler_and_source_observability(client, db_session) -> None:
    now = datetime.now(timezone.utc)
    due_user = User(email="owner-due@example.com")
    checked_user = User(email="owner-checked@example.com")
    db_session.add_all([due_user, checked_user])
    db_session.flush()

    due_source = Input(
        user_id=due_user.id,
        type=InputType.ICS,
        name="due-source",
        normalized_name="due-source",
        encrypted_url="encrypted-1",
        interval_minutes=15,
        is_active=True,
        last_checked_at=None,
    )
    checked_source = Input(
        user_id=checked_user.id,
        type=InputType.ICS,
        name="checked-source",
        normalized_name="checked-source",
        encrypted_url="encrypted-2",
        interval_minutes=15,
        is_active=True,
        last_checked_at=now - timedelta(minutes=2),
    )
    db_session.add_all([due_source, checked_source])
    db_session.flush()

    db_session.add_all(
        [
            SyncRun(
                input_id=checked_source.id,
                trigger_type=SyncTriggerType.SCHEDULER,
                started_at=now - timedelta(minutes=10),
                finished_at=now - timedelta(minutes=10),
                status=SyncRunStatus.FETCH_FAILED,
                changes_count=0,
                duration_ms=300,
            ),
            SyncRun(
                input_id=checked_source.id,
                trigger_type=SyncTriggerType.SCHEDULER,
                started_at=now - timedelta(minutes=30),
                finished_at=now - timedelta(minutes=30),
                status=SyncRunStatus.LOCK_SKIPPED,
                changes_count=0,
                duration_ms=0,
            ),
            SyncRun(
                input_id=checked_source.id,
                trigger_type=SyncTriggerType.SCHEDULER,
                started_at=now - timedelta(hours=3),
                finished_at=now - timedelta(hours=3),
                status=SyncRunStatus.DIFF_FAILED,
                changes_count=0,
                duration_ms=200,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/v1/status", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    payload = response.json()

    assert payload["scheduler_last_tick_at"] is None
    assert payload["scheduler_lock_acquired"] is None
    assert payload["due_inputs_count"] == 1
    assert payload["checked_in_last_5m_count"] == 1
    assert payload["failed_in_last_1h_count"] == 1
    assert payload["schema_guard_blocked"] is False
    assert payload["schema_guard_message"] is None


def test_status_api_due_inputs_count_skips_recent_scheduler_lock_skipped_source(client, db_session) -> None:
    now = datetime.now(timezone.utc)
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Input(
        user_id=user.id,
        type=InputType.ICS,
        name="locked-source",
        normalized_name="locked-source",
        encrypted_url="encrypted-locked",
        interval_minutes=15,
        is_active=True,
        last_checked_at=now - timedelta(minutes=20),
    )
    db_session.add(source)
    db_session.flush()

    db_session.add(
        SyncRun(
            input_id=source.id,
            trigger_type=SyncTriggerType.SCHEDULER,
            started_at=now - timedelta(seconds=10),
            finished_at=now - timedelta(seconds=10),
            status=SyncRunStatus.LOCK_SKIPPED,
            changes_count=0,
            duration_ms=0,
        )
    )
    db_session.commit()

    response = client.get("/v1/status", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["due_inputs_count"] == 0
