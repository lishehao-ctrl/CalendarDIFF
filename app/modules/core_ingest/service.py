from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import IngestApplyLog, IngestResult, SyncRequest, SyncRequestStatus


def get_ingest_apply_status(db: Session, *, request_id: str) -> dict:
    result = db.scalar(select(IngestResult).where(IngestResult.request_id == request_id))
    apply_log = db.scalar(select(IngestApplyLog).where(IngestApplyLog.request_id == request_id))
    return {
        "request_id": request_id,
        "result_exists": result is not None,
        "result_status": result.status.value if result is not None else None,
        "applied": apply_log is not None,
        "applied_at": apply_log.applied_at if apply_log is not None else None,
    }


def apply_ingest_result_idempotent(db: Session, *, request_id: str) -> dict:
    now = datetime.now(timezone.utc)
    result = db.scalar(select(IngestResult).where(IngestResult.request_id == request_id))
    if result is None:
        raise RuntimeError("Ingest result not found")

    try:
        db.add(
            IngestApplyLog(
                request_id=request_id,
                applied_at=now,
                status="applied",
                error_message=None,
            )
        )
        sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == request_id))
        if sync_request is not None and sync_request.status != SyncRequestStatus.FAILED:
            sync_request.status = SyncRequestStatus.SUCCEEDED
        db.commit()
        return {
            "request_id": request_id,
            "applied": True,
            "idempotent_replay": False,
            "changes_created": 0,
        }
    except IntegrityError:
        db.rollback()
        return {
            "request_id": request_id,
            "applied": True,
            "idempotent_replay": True,
            "changes_created": 0,
        }
