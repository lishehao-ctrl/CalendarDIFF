from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.ingestion import IngestResult
from app.db.models.review import IngestApplyLog
from app.db.models.input import InputSource, SyncRequest, SyncRequestStatus
from app.modules.core_ingest.apply_orchestrator import apply_records


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

    sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == request_id))
    source = db.get(InputSource, result.source_id)
    if source is None:
        raise RuntimeError("Input source not found for ingest result")

    try:
        db.add(
            IngestApplyLog(
                request_id=request_id,
                applied_at=now,
                status="applied",
                error_message=None,
            )
        )
        db.flush()
    except IntegrityError:
        db.rollback()
        return {
            "request_id": request_id,
            "applied": True,
            "idempotent_replay": True,
            "changes_created": 0,
        }

    try:
        changes_created = apply_records(
            db=db,
            result=result,
            source=source,
            applied_at=now,
            request_id=request_id,
        )
        if sync_request is not None and sync_request.status != SyncRequestStatus.FAILED:
            sync_request.status = SyncRequestStatus.SUCCEEDED
            sync_request.error_code = None
            sync_request.error_message = None
        db.commit()
        return {
            "request_id": request_id,
            "applied": True,
            "idempotent_replay": False,
            "changes_created": changes_created,
        }
    except Exception:
        db.rollback()
        raise


__all__ = ["apply_ingest_result_idempotent", "get_ingest_apply_status"]
