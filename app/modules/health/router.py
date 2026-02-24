from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.logging import sanitize_log_message
from app.db.models import Input
from app.db.session import get_db
from app.modules.scheduler.runner import SchedulerRunner
from app.state import SchedulerStatus

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    db_ok = False
    db_error: str | None = None
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:  # pragma: no cover - defensive path
        db_error = sanitize_log_message(str(exc))

    runner: SchedulerRunner | None = getattr(request.app.state, "scheduler_runner", None)
    scheduler_summary = runner.status.to_dict() if runner else SchedulerStatus().to_dict()

    next_input_id: int | None = None
    next_check_at: datetime | None = None
    if db_ok:
        try:
            next_input_id, next_check_at = _compute_next_expected_check(db, now=now)
        except Exception as exc:  # pragma: no cover - defensive path
            db_ok = False
            db_error = sanitize_log_message(str(exc))

    scheduler_summary["next_expected_input_id"] = next_input_id
    scheduler_summary["next_expected_check_at"] = next_check_at
    if db_ok:
        scheduler_summary["database_dialect"] = db.get_bind().dialect.name
        scheduler_summary["lock_backend"] = "postgres_advisory"

    return {
        "status": "ok" if db_ok else "degraded",
        "timestamp": now.isoformat(),
        "db": {"ok": db_ok, "error": db_error},
        "scheduler": scheduler_summary,
    }


def _compute_next_expected_check(db: Session, now: datetime) -> tuple[int | None, datetime | None]:
    next_check_expr = func.coalesce(
        Input.last_checked_at + func.make_interval(0, 0, 0, 0, 0, Input.interval_minutes, 0),
        now,
    )
    stmt = (
        select(Input.id, next_check_expr.label("next_check_at"))
        .where(Input.is_active.is_(True))
        .order_by(next_check_expr.asc(), Input.id.asc())
        .limit(1)
    )
    row = db.execute(stmt).first()
    if row is None:
        return None, None

    input_id, next_check_at = row
    if next_check_at is None:
        return None, None
    return input_id, _as_utc(next_check_at)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
