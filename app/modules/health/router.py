from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import sanitize_log_message
from app.db.session import get_db
from app.modules.scheduler.runner import SchedulerRunner

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    db_ok = False
    db_error: str | None = None
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:  # pragma: no cover - defensive path
        db_error = sanitize_log_message(str(exc))

    runner: SchedulerRunner | None = getattr(request.app.state, "scheduler_runner", None)
    scheduler_summary = runner.status.to_dict() if runner else {}

    return {
        "status": "ok" if db_ok else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "db": {"ok": db_ok, "error": db_error},
        "scheduler": scheduler_summary,
    }
