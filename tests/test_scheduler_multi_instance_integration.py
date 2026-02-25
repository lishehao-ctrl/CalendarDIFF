from __future__ import annotations

import threading
from datetime import datetime, timezone

from app.db.models import Input, InputType, User
from app.modules.scheduler.runner import SchedulerRunner
from app.modules.sync.service import SyncRunResult
from app.state import SchedulerStatus


def test_dual_scheduler_runners_share_global_lock(db_session, db_session_factory, monkeypatch) -> None:
    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Input(
        user_id=user.id,
        type=InputType.ICS,
        name="multi-instance",
        normalized_name="multi-instance",
        encrypted_url="encrypted",
        interval_minutes=15,
        is_active=True,
        last_checked_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    db_session.commit()

    status_a = SchedulerStatus()
    status_b = SchedulerStatus()
    runner_a = SchedulerRunner(db_session_factory, status_a)
    runner_b = SchedulerRunner(db_session_factory, status_b)

    monkeypatch.setattr("app.modules.scheduler.runner.list_due_inputs", lambda db: [source])

    sync_calls = 0
    sync_lock = threading.Lock()
    sync_started = threading.Event()
    allow_finish = threading.Event()

    def fake_sync_input(db, src, **kwargs):  # noqa: ANN001, ARG001
        del db
        assert src.id == source.id
        nonlocal sync_calls
        with sync_lock:
            sync_calls += 1
        sync_started.set()
        allow_finish.wait(timeout=5)
        return SyncRunResult(
            input_id=source.id,
            changes_created=0,
            email_sent=False,
            last_error=None,
        )

    monkeypatch.setattr("app.modules.scheduler.runner.sync_input", fake_sync_input)

    thread_a = threading.Thread(target=runner_a._tick)
    thread_a.start()
    assert sync_started.wait(timeout=5)

    runner_b._tick()

    allow_finish.set()
    thread_a.join(timeout=5)

    assert sync_calls == 1
    assert status_a.cumulative_run_executed_count == 1
    assert status_b.cumulative_run_executed_count == 0
    assert status_b.cumulative_run_skipped_lock_count == 1
    assert status_b.last_skip_reason == "lock_not_acquired"
