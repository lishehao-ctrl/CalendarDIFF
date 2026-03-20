from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.logging import sanitize_log_message
from app.db.models.input import InputSource
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    db_ok = False
    db_error: str | None = None
    schema_guard_error = getattr(request.app.state, "schema_guard_error", None)
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:  # pragma: no cover - defensive path
        db_error = sanitize_log_message(str(exc))

    scheduler_summary = _default_scheduler_summary()

    next_source_id: int | None = None
    next_check_at: datetime | None = None
    if db_ok:
        try:
            next_source_id, next_check_at = _compute_next_expected_check(db, now=now)
        except Exception as exc:  # pragma: no cover - defensive path
            db_ok = False
            db_error = sanitize_log_message(str(exc))

    scheduler_summary["next_expected_source_id"] = next_source_id
    scheduler_summary["next_expected_check_at"] = next_check_at
    if db_ok:
        scheduler_summary["database_dialect"] = db.get_bind().dialect.name
        scheduler_summary["lock_backend"] = "postgres_advisory"
    scheduler_summary["schema_guard_blocked"] = bool(schema_guard_error)
    scheduler_summary["schema_guard_message"] = schema_guard_error

    return {
        "status": "ok" if db_ok else "degraded",
        "timestamp": now.isoformat(),
        "db": {"ok": db_ok, "error": db_error},
        "scheduler": scheduler_summary,
    }


def _compute_next_expected_check(db: Session, now: datetime) -> tuple[int | None, datetime | None]:
    stmt = (
        select(InputSource.id, InputSource.next_poll_at)
        .where(InputSource.is_active.is_(True))
        .order_by(InputSource.next_poll_at.asc().nullslast(), InputSource.id.asc())
        .limit(1)
    )
    row = db.execute(stmt).first()
    if row is None:
        return None, None

    source_id, next_check_at = row
    if next_check_at is None:
        return source_id, now
    return source_id, _as_utc(next_check_at)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _default_scheduler_summary() -> dict[str, object]:
    return {
        "running": False,
        "instance_id": None,
        "last_tick_at": None,
        "last_tick_lock_acquired": None,
        "last_run_started_at": None,
        "last_run_finished_at": None,
        "last_error": None,
        "last_skip_reason": None,
        "last_synced_sources": 0,
        "last_run_success_count": 0,
        "last_run_failed_count": 0,
        "last_run_notification_failed_count": 0,
        "cumulative_success_count": 0,
        "cumulative_failed_count": 0,
        "cumulative_notification_failed_count": 0,
        "cumulative_run_executed_count": 0,
        "cumulative_run_skipped_lock_count": 0,
        "next_expected_check_at": None,
        "next_expected_source_id": None,
        "lock_backend": "postgres_advisory",
        "database_dialect": "postgresql",
        "schema_guard_blocked": False,
        "schema_guard_message": None,
    }
