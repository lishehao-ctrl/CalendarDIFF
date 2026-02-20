from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.logging import sanitize_log_message
from app.db.models import Source
from app.modules.sync.service import list_due_sources, sync_source
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
        self._status.running = True
        self._status.last_run_started_at = datetime.now(timezone.utc)
        self._status.last_skip_reason = None
        self._status.last_error = None
        self._status.last_synced_sources = 0

        settings = get_settings()
        db = self._session_factory()
        lock_acquired = False
        try:
            lock_acquired = try_acquire_global_lock(db, settings.global_scheduler_lock_key)
            if not lock_acquired:
                self._status.last_skip_reason = "lock_not_acquired"
                return

            due_sources = list_due_sources(db)
            synced_count = 0
            for source in due_sources:
                if not try_acquire_source_lock(db, settings.source_lock_namespace, source.id):
                    continue
                try:
                    sync_source(db, source)
                    synced_count += 1
                finally:
                    release_source_lock(db, settings.source_lock_namespace, source.id)

            self._status.last_synced_sources = synced_count
        except Exception as exc:
            safe_error = sanitize_log_message(str(exc))
            self._status.last_error = safe_error
            logger.error("scheduler tick failed error=%s", safe_error)
        finally:
            if lock_acquired:
                release_global_lock(db, settings.global_scheduler_lock_key)
            db.close()
            self._status.running = False
            self._status.last_run_finished_at = datetime.now(timezone.utc)


def _is_postgres(db: Session) -> bool:
    bind = db.get_bind()
    return bind.dialect.name.startswith("postgresql")


def try_acquire_global_lock(db: Session, lock_key: int) -> bool:
    if not _is_postgres(db):
        return True

    stmt = text("SELECT pg_try_advisory_lock(:lock_key)")
    return bool(db.execute(stmt, {"lock_key": lock_key}).scalar_one())


def release_global_lock(db: Session, lock_key: int) -> None:
    if not _is_postgres(db):
        return

    stmt = text("SELECT pg_advisory_unlock(:lock_key)")
    db.execute(stmt, {"lock_key": lock_key})


def try_acquire_source_lock(db: Session, namespace: int, source_id: int) -> bool:
    if not _is_postgres(db):
        return True

    stmt = text("SELECT pg_try_advisory_lock(:ns, :source_id)")
    return bool(db.execute(stmt, {"ns": namespace, "source_id": source_id}).scalar_one())


def release_source_lock(db: Session, namespace: int, source_id: int) -> None:
    if not _is_postgres(db):
        return

    stmt = text("SELECT pg_advisory_unlock(:ns, :source_id)")
    db.execute(stmt, {"ns": namespace, "source_id": source_id})
