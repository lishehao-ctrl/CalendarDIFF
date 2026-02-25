from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import delete, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.logging import sanitize_log_message
from app.db.models import Input, SyncRun, SyncRunStatus, SyncTriggerType
from app.modules.notify.digest_service import process_due_digests
from app.modules.notify.service import dispatch_due_notifications
from app.modules.sync.service import list_due_inputs, record_lock_skipped_run, sync_input
from app.state import SchedulerStatus

logger = logging.getLogger(__name__)


class SchedulerRunner:
    def __init__(self, session_factory: sessionmaker[Session], status: SchedulerStatus) -> None:
        self._session_factory = session_factory
        self._status = status
        self._scheduler = BackgroundScheduler(timezone="UTC")
        self._started = False

    @property
    def status(self) -> SchedulerStatus:
        return self._status

    def start(self) -> None:
        if self._started:
            return

        settings = get_settings()
        self._scheduler.add_job(
            self._tick,
            trigger="interval",
            seconds=settings.scheduler_tick_seconds,
            max_instances=1,
            coalesce=True,
            id="deadline_diff_scheduler_tick",
        )
        self._scheduler.start()
        self._started = True
        logger.info("scheduler started")

    def stop(self) -> None:
        if not self._started:
            return
        self._scheduler.shutdown(wait=False)
        self._started = False
        logger.info("scheduler stopped")

    def _tick(self) -> None:
        tick_started_at = datetime.now(timezone.utc)
        self._status.running = True
        self._status.last_tick_at = tick_started_at
        self._status.last_tick_lock_acquired = None
        self._status.last_run_started_at = tick_started_at
        self._status.last_skip_reason = None
        self._status.last_error = None

        settings = get_settings()
        db = self._session_factory()
        self._status.database_dialect = db.get_bind().dialect.name
        self._status.lock_backend = "postgres_advisory"
        lock_acquired = False
        run_success_count = 0
        run_failed_count = 0
        run_notification_failed_count = 0
        run_synced_inputs = 0
        try:
            lock_acquired = try_acquire_global_lock(db, settings.global_scheduler_lock_key)
            if not lock_acquired:
                self._status.last_tick_lock_acquired = False
                self._status.last_skip_reason = "lock_not_acquired"
                self._status.cumulative_run_skipped_lock_count += 1
                return

            self._status.last_tick_lock_acquired = True
            self._status.cumulative_run_executed_count += 1
            due_inputs = list_due_inputs(db)
            for input in due_inputs:
                if not try_acquire_source_lock(db, settings.source_lock_namespace, input.id):
                    record_lock_skipped_run(
                        db,
                        input_id=input.id,
                        trigger_type=SyncTriggerType.SCHEDULER,
                        lock_owner=self._status.instance_id,
                    )
                    continue
                try:
                    try:
                        result = sync_input(
                            db,
                            input,
                            trigger_type=SyncTriggerType.SCHEDULER,
                            lock_owner=self._status.instance_id,
                        )
                    except Exception as exc:
                        _handle_source_sync_exception(
                            db,
                            input_id=input.id,
                            exc=exc,
                            lock_owner=self._status.instance_id,
                        )
                        run_failed_count += 1
                        continue
                    if result.status in {
                        SyncRunStatus.FETCH_FAILED,
                        SyncRunStatus.PARSE_FAILED,
                        SyncRunStatus.DIFF_FAILED,
                    }:
                        run_failed_count += 1
                    elif result.status == SyncRunStatus.EMAIL_FAILED:
                        run_notification_failed_count += 1
                        run_synced_inputs += 1
                    else:
                        run_success_count += 1
                        run_synced_inputs += 1
                finally:
                    release_source_lock(db, settings.source_lock_namespace, input.id)

            due_dispatch_result = dispatch_due_notifications(db, now=datetime.now(timezone.utc))
            if due_dispatch_result.failed_by_source_id:
                run_notification_failed_count += len(due_dispatch_result.failed_by_source_id)

            digest_lock_acquired = try_acquire_global_lock(db, settings.digest_scheduler_lock_key)
            if digest_lock_acquired:
                try:
                    process_due_digests(db, now=datetime.now(timezone.utc))
                finally:
                    release_global_lock(db, settings.digest_scheduler_lock_key)

            _cleanup_old_sync_runs(
                db,
                status=self._status,
                retention_days=settings.sync_runs_retention_days,
            )
        except Exception as exc:
            safe_error = sanitize_log_message(str(exc))
            self._status.last_error = safe_error
            logger.error("scheduler tick failed error=%s", safe_error)
        finally:
            if lock_acquired:
                self._status.last_synced_sources = run_synced_inputs
                self._status.last_run_success_count = run_success_count
                self._status.last_run_failed_count = run_failed_count
                self._status.last_run_notification_failed_count = run_notification_failed_count
                self._status.cumulative_success_count += run_success_count
                self._status.cumulative_failed_count += run_failed_count
                self._status.cumulative_notification_failed_count += run_notification_failed_count
            if lock_acquired:
                release_global_lock(db, settings.global_scheduler_lock_key)
            db.close()
            self._status.running = False
            self._status.last_run_finished_at = datetime.now(timezone.utc)


def _assert_postgres(db: Session) -> None:
    bind = db.get_bind()
    if bind.dialect.name.startswith("postgresql"):
        return
    raise RuntimeError(
        "PostgreSQL-only scheduler lock path requires PostgreSQL dialect, "
        f"got '{bind.dialect.name}'."
    )


def try_acquire_global_lock(db: Session, lock_key: int) -> bool:
    _assert_postgres(db)
    stmt = text("SELECT pg_try_advisory_lock(:lock_key)")
    return bool(db.execute(stmt, {"lock_key": lock_key}).scalar_one())


def release_global_lock(db: Session, lock_key: int) -> None:
    _assert_postgres(db)
    stmt = text("SELECT pg_advisory_unlock(:lock_key)")
    db.execute(stmt, {"lock_key": lock_key})


def try_acquire_source_lock(db: Session, namespace: int, input_id: int) -> bool:
    _assert_postgres(db)
    stmt = text("SELECT pg_try_advisory_lock(:ns, :input_id)")
    return bool(db.execute(stmt, {"ns": namespace, "input_id": input_id}).scalar_one())


def acquire_source_lock_blocking(db: Session, namespace: int, input_id: int) -> None:
    _assert_postgres(db)
    stmt = text("SELECT pg_advisory_lock(:ns, :input_id)")
    db.execute(stmt, {"ns": namespace, "input_id": input_id})


def release_source_lock(db: Session, namespace: int, input_id: int) -> None:
    _assert_postgres(db)
    stmt = text("SELECT pg_advisory_unlock(:ns, :input_id)")
    db.execute(stmt, {"ns": namespace, "input_id": input_id})


def _handle_source_sync_exception(db: Session, *, input_id: int, exc: Exception, lock_owner: str | None) -> None:
    safe_error = sanitize_log_message(str(exc))
    logger.error("scheduler input sync failed input_id=%s error=%s", input_id, safe_error)
    db.rollback()
    input = db.get(Input, input_id)
    now = datetime.now(timezone.utc)
    run = SyncRun(
        input_id=input_id,
        trigger_type=SyncTriggerType.SCHEDULER,
        started_at=now,
        finished_at=now,
        status=SyncRunStatus.DIFF_FAILED,
        changes_count=0,
        error_code="diff_exception",
        error_message=safe_error[:512],
        lock_owner=lock_owner,
        duration_ms=0,
    )
    if input is not None:
        input.last_checked_at = now
        input.last_error_at = now
        input.last_error = safe_error
    db.add(run)
    db.commit()


def _cleanup_old_sync_runs(db: Session, *, status: SchedulerStatus, retention_days: int) -> None:
    now = datetime.now(timezone.utc)
    if retention_days <= 0:
        return
    if status.last_retention_cleanup_at is not None:
        if now - status.last_retention_cleanup_at < timedelta(hours=24):
            return

    cutoff = now - timedelta(days=retention_days)
    try:
        db.execute(
            delete(SyncRun).where(
                SyncRun.finished_at.is_not(None),
                SyncRun.finished_at < cutoff,
            )
        )
        db.commit()
        status.last_retention_cleanup_at = now
    except Exception as exc:
        db.rollback()
        logger.error("sync run retention cleanup failed error=%s", sanitize_log_message(str(exc)))
