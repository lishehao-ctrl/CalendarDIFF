from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import Source, SourceType, SyncRun, SyncRunStatus, SyncTriggerType, User
from app.modules.scheduler.runner import SchedulerRunner, release_global_lock, try_acquire_global_lock
from app.modules.sync.service import SyncRunResult, list_due_sources
from app.state import SchedulerStatus


def test_list_due_sources_respects_interval_minutes(db_session) -> None:
    now = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)

    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    due_never_checked = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name="due-never",
        normalized_name="due-never",
        encrypted_url="encrypted-1",
        interval_minutes=15,
        is_active=True,
        last_checked_at=None,
    )
    not_due_yet = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name="not-due",
        normalized_name="not-due",
        encrypted_url="encrypted-2",
        interval_minutes=15,
        is_active=True,
        last_checked_at=now - timedelta(minutes=5),
    )
    due_by_elapsed_time = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name="due-elapsed",
        normalized_name="due-elapsed",
        encrypted_url="encrypted-3",
        interval_minutes=15,
        is_active=True,
        last_checked_at=now - timedelta(minutes=20),
    )
    db_session.add_all([due_never_checked, not_due_yet, due_by_elapsed_time])
    db_session.commit()

    due_sources = list_due_sources(db_session, now=now)
    due_ids = {source.id for source in due_sources}

    assert due_never_checked.id in due_ids
    assert due_by_elapsed_time.id in due_ids
    assert not_due_yet.id not in due_ids


def test_list_due_sources_skips_recent_scheduler_lock_skipped_source(db_session) -> None:
    now = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)

    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name="locked-recently",
        normalized_name="locked-recently",
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
            error_code="source_lock_not_acquired",
            duration_ms=0,
        )
    )
    db_session.commit()

    due_now = list_due_sources(db_session, now=now)
    assert source.id not in {item.id for item in due_now}

    due_after_cooldown = list_due_sources(db_session, now=now + timedelta(seconds=31))
    assert source.id in {item.id for item in due_after_cooldown}


def test_global_advisory_lock_allows_single_holder(db_session_factory) -> None:
    session_a = db_session_factory()
    session_b = db_session_factory()
    lock_key = 991122
    b_holds_lock = False
    try:
        assert try_acquire_global_lock(session_a, lock_key) is True
        assert try_acquire_global_lock(session_b, lock_key) is False

        release_global_lock(session_a, lock_key)
        assert try_acquire_global_lock(session_b, lock_key) is True
        b_holds_lock = True
    finally:
        if b_holds_lock:
            release_global_lock(session_b, lock_key)
        session_a.close()
        session_b.close()


def test_scheduler_tick_tracks_success_failure_and_notification_failure(db_session, db_session_factory, monkeypatch) -> None:
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source_sync_failed = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name="sync-failed",
        normalized_name="sync-failed",
        encrypted_url="encrypted-1",
        interval_minutes=15,
        is_active=True,
    )
    source_notification_failed = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name="notification-failed",
        normalized_name="notification-failed",
        encrypted_url="encrypted-2",
        interval_minutes=15,
        is_active=True,
    )
    source_success = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name="success",
        normalized_name="success",
        encrypted_url="encrypted-3",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add_all([source_sync_failed, source_notification_failed, source_success])
    db_session.commit()

    due_sources = [source_sync_failed, source_notification_failed, source_success]

    status = SchedulerStatus()
    runner = SchedulerRunner(db_session_factory, status)

    monkeypatch.setattr("app.modules.scheduler.runner.try_acquire_global_lock", lambda db, key: True)
    monkeypatch.setattr("app.modules.scheduler.runner.release_global_lock", lambda db, key: None)
    monkeypatch.setattr("app.modules.scheduler.runner.try_acquire_source_lock", lambda db, ns, source_id: True)
    monkeypatch.setattr("app.modules.scheduler.runner.release_source_lock", lambda db, ns, source_id: None)
    monkeypatch.setattr("app.modules.scheduler.runner.list_due_sources", lambda db: due_sources)

    def fake_sync_source(db, source, **kwargs):  # noqa: ANN001, ARG001
        if source.id == source_sync_failed.id:
            return SyncRunResult(
                input_id=source.id,
                changes_created=0,
                email_sent=False,
                last_error="fetch failed",
                is_baseline_sync=False,
                sync_failed=True,
                status=SyncRunStatus.FETCH_FAILED,
                error_code="fetch_timeout",
            )
        if source.id == source_notification_failed.id:
            return SyncRunResult(
                input_id=source.id,
                changes_created=1,
                email_sent=False,
                last_error="smtp failed",
                is_baseline_sync=False,
                notification_failed=True,
                status=SyncRunStatus.EMAIL_FAILED,
                error_code="email_send_failed",
            )
        return SyncRunResult(
            input_id=source.id,
            changes_created=1,
            email_sent=True,
            last_error=None,
            is_baseline_sync=False,
            status=SyncRunStatus.CHANGED,
        )

    monkeypatch.setattr("app.modules.scheduler.runner.sync_source", fake_sync_source)

    runner._tick()

    assert status.last_run_success_count == 1
    assert status.last_run_failed_count == 1
    assert status.last_run_notification_failed_count == 1
    assert status.last_synced_sources == 2
    assert status.cumulative_success_count == 1
    assert status.cumulative_failed_count == 1
    assert status.cumulative_notification_failed_count == 1
    assert status.cumulative_run_executed_count == 1
    assert status.cumulative_run_skipped_lock_count == 0
    assert status.last_skip_reason is None
    assert status.last_error is None
    assert status.last_run_started_at is not None
    assert status.last_run_finished_at is not None


def test_scheduler_tick_lock_skip_increments_skip_counter(db_session_factory, monkeypatch) -> None:
    status = SchedulerStatus(
        last_run_success_count=7,
        last_run_failed_count=2,
        last_run_notification_failed_count=1,
        last_synced_sources=8,
    )
    runner = SchedulerRunner(db_session_factory, status)

    monkeypatch.setattr("app.modules.scheduler.runner.try_acquire_global_lock", lambda db, key: False)

    runner._tick()

    assert status.last_skip_reason == "lock_not_acquired"
    assert status.cumulative_run_skipped_lock_count == 1
    assert status.cumulative_run_executed_count == 0
    # lock skipped run should not overwrite the most recent executed-run counters
    assert status.last_run_success_count == 7
    assert status.last_run_failed_count == 2
    assert status.last_run_notification_failed_count == 1
    assert status.last_synced_sources == 8


def test_scheduler_tick_records_lock_skipped_run_for_source_conflict(db_session, db_session_factory, monkeypatch) -> None:
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name="locked-source",
        normalized_name="locked-source",
        encrypted_url="encrypted-locked",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(source)
    db_session.commit()

    status = SchedulerStatus()
    runner = SchedulerRunner(db_session_factory, status)

    monkeypatch.setattr("app.modules.scheduler.runner.try_acquire_global_lock", lambda db, key: True)
    monkeypatch.setattr("app.modules.scheduler.runner.release_global_lock", lambda db, key: None)
    monkeypatch.setattr("app.modules.scheduler.runner.list_due_sources", lambda db: [source])
    monkeypatch.setattr("app.modules.scheduler.runner.try_acquire_source_lock", lambda db, ns, source_id: False)

    runner._tick()

    db_session.expire_all()
    sync_runs = db_session.query(SyncRun).all()
    assert len(sync_runs) == 1
    assert sync_runs[0].status == SyncRunStatus.LOCK_SKIPPED
    assert sync_runs[0].trigger_type == SyncTriggerType.SCHEDULER
    assert status.last_run_success_count == 0
    assert status.last_run_failed_count == 0
    assert status.last_run_notification_failed_count == 0


def test_scheduler_tick_isolates_unexpected_source_exception(db_session, db_session_factory, monkeypatch) -> None:
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source_broken = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name="broken",
        normalized_name="broken",
        encrypted_url="encrypted-broken",
        interval_minutes=15,
        is_active=True,
    )
    source_success = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name="success",
        normalized_name="success",
        encrypted_url="encrypted-success",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add_all([source_broken, source_success])
    db_session.commit()

    due_sources = [source_broken, source_success]

    status = SchedulerStatus()
    runner = SchedulerRunner(db_session_factory, status)

    monkeypatch.setattr("app.modules.scheduler.runner.try_acquire_global_lock", lambda db, key: True)
    monkeypatch.setattr("app.modules.scheduler.runner.release_global_lock", lambda db, key: None)
    monkeypatch.setattr("app.modules.scheduler.runner.try_acquire_source_lock", lambda db, ns, source_id: True)
    monkeypatch.setattr("app.modules.scheduler.runner.release_source_lock", lambda db, ns, source_id: None)
    monkeypatch.setattr("app.modules.scheduler.runner.list_due_sources", lambda db: due_sources)

    def fake_sync_source(db, source, **kwargs):  # noqa: ANN001, ARG001
        if source.id == source_broken.id:
            raise RuntimeError("unexpected parser crash")
        return SyncRunResult(
            input_id=source.id,
            changes_created=1,
            email_sent=True,
            last_error=None,
            status=SyncRunStatus.CHANGED,
        )

    monkeypatch.setattr("app.modules.scheduler.runner.sync_source", fake_sync_source)

    runner._tick()

    assert status.last_run_success_count == 1
    assert status.last_run_failed_count == 1
    assert status.last_synced_sources == 1

    db_session.expire_all()
    broken = db_session.get(Source, source_broken.id)
    assert broken is not None
    assert broken.last_error is not None


def test_scheduler_tick_cleans_up_old_sync_runs_once_per_day(db_session, db_session_factory, monkeypatch) -> None:
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name="cleanup-source",
        normalized_name="cleanup-source",
        encrypted_url="encrypted-cleanup",
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(source)
    db_session.flush()

    now = datetime.now(timezone.utc)
    old_run = SyncRun(
        input_id=source.id,
        trigger_type=SyncTriggerType.SCHEDULER,
        started_at=now - timedelta(days=31),
        finished_at=now - timedelta(days=31),
        status=SyncRunStatus.NO_CHANGE,
        changes_count=0,
        duration_ms=100,
    )
    recent_run = SyncRun(
        input_id=source.id,
        trigger_type=SyncTriggerType.SCHEDULER,
        started_at=now - timedelta(days=2),
        finished_at=now - timedelta(days=2),
        status=SyncRunStatus.NO_CHANGE,
        changes_count=0,
        duration_ms=90,
    )
    db_session.add_all([old_run, recent_run])
    db_session.commit()
    old_run_id = old_run.id
    recent_run_id = recent_run.id

    status = SchedulerStatus()
    runner = SchedulerRunner(db_session_factory, status)

    monkeypatch.setattr("app.modules.scheduler.runner.try_acquire_global_lock", lambda db, key: True)
    monkeypatch.setattr("app.modules.scheduler.runner.release_global_lock", lambda db, key: None)
    monkeypatch.setattr("app.modules.scheduler.runner.list_due_sources", lambda db: [])

    runner._tick()

    db_session.expire_all()
    remaining_ids = {run.id for run in db_session.query(SyncRun).all()}
    assert old_run_id not in remaining_ids
    assert recent_run_id in remaining_ids
    assert status.last_retention_cleanup_at is not None

    # Second tick within 24h should skip cleanup.
    stale_again = SyncRun(
        input_id=source.id,
        trigger_type=SyncTriggerType.SCHEDULER,
        started_at=now - timedelta(days=40),
        finished_at=now - timedelta(days=40),
        status=SyncRunStatus.NO_CHANGE,
        changes_count=0,
        duration_ms=80,
    )
    db_session.add(stale_again)
    db_session.commit()
    stale_again_id = stale_again.id

    cleanup_mark = status.last_retention_cleanup_at
    runner._tick()

    db_session.expire_all()
    stale_exists = db_session.get(SyncRun, stale_again_id)
    assert stale_exists is not None
    assert status.last_retention_cleanup_at == cleanup_mark
