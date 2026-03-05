from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IngestApplyLog, IngestResult, SyncRequest


def build_sync_request_status_payload(db: Session, *, sync_request: SyncRequest) -> dict:
    result = db.scalar(select(IngestResult).where(IngestResult.request_id == sync_request.request_id))
    apply_log = db.scalar(select(IngestApplyLog).where(IngestApplyLog.request_id == sync_request.request_id))
    connector_result: dict | None = None
    if result is not None:
        connector_result = {
            "provider": result.provider,
            "status": result.status.value,
            "fetched_at": result.fetched_at,
            "error_code": result.error_code,
            "error_message": result.error_message,
            "records_count": len(result.records or []),
        }
    return {
        "request_id": sync_request.request_id,
        "source_id": sync_request.source_id,
        "trigger_type": sync_request.trigger_type.value,
        "status": sync_request.status.value,
        "idempotency_key": sync_request.idempotency_key,
        "trace_id": sync_request.trace_id,
        "error_code": sync_request.error_code,
        "error_message": sync_request.error_message,
        "metadata": sync_request.metadata_json or {},
        "created_at": sync_request.created_at,
        "updated_at": sync_request.updated_at,
        "connector_result": connector_result,
        "applied": apply_log is not None,
        "applied_at": apply_log.applied_at if apply_log is not None else None,
    }


__all__ = ["build_sync_request_status_payload"]
