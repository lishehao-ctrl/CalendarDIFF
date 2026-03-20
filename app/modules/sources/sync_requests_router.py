from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models.input import IngestTriggerType
from app.db.models.shared import User
from app.db.session import get_db
from app.modules.auth.deps import get_authenticated_user_or_401
from app.modules.common.source_monitoring_window import parse_source_monitoring_window, source_timezone_name
from app.modules.sources.router_common import require_owned_source_or_404
from app.modules.sources.schemas import (
    SyncRequestCreateRequest,
    SyncRequestCreateResponse,
    SyncRequestStatusResponse,
)
from app.modules.sources.source_monitoring_window_rebind import has_pending_monitoring_window_update
from app.modules.sources.status_projection import build_sync_request_status_payload
from app.modules.sources.sync_requests_service import enqueue_sync_request_idempotent, get_sync_request_status

router = APIRouter()


@router.post("/sources/{source_id}/sync-requests", response_model=SyncRequestCreateResponse, status_code=status.HTTP_201_CREATED)
def create_sync_request(
    source_id: int,
    payload: SyncRequestCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> SyncRequestCreateResponse:
    source = require_owned_source_or_404(db=db, user_id=user.id, source_id=source_id)
    if has_pending_monitoring_window_update(source):
        raise HTTPException(
            status_code=409,
            detail={"code": "source_monitoring_window_update_pending", "message": "source monitoring window update is pending"},
        )
    term_window = parse_source_monitoring_window(source, required=False)
    now = datetime.now(timezone.utc)
    if term_window is not None and not term_window.has_started(now=now, timezone_name=source_timezone_name(source)):
        raise HTTPException(
            status_code=409,
            detail={"code": "source_monitoring_not_started", "message": "source monitoring has not started yet"},
        )
    if not source.is_active:
        raise HTTPException(
            status_code=409,
            detail={"code": "source_inactive", "message": "source is inactive and cannot be synced"},
        )
    applied_idempotency_key = idempotency_key or f"manual:{source_id}:{uuid4().hex}"
    row = enqueue_sync_request_idempotent(
        db,
        source=source,
        trigger_type=IngestTriggerType.MANUAL,
        idempotency_key=applied_idempotency_key,
        metadata=payload.metadata or {"kind": "manual"},
        trace_id=payload.trace_id,
    )
    return SyncRequestCreateResponse(
        request_id=row.request_id,
        source_id=row.source_id,
        trigger_type=row.trigger_type.value,  # type: ignore[arg-type]
        status=row.status.value,  # type: ignore[arg-type]
        created_at=row.created_at,
        idempotency_key=row.idempotency_key,
    )


@router.get("/sync-requests/{request_id}", response_model=SyncRequestStatusResponse)
def get_sync_request(
    request_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> SyncRequestStatusResponse:
    row = get_sync_request_status(db, request_id=request_id)
    if row is None or row.source.user_id != user.id:
        raise HTTPException(status_code=404, detail="Sync request not found")
    return SyncRequestStatusResponse.model_validate(build_sync_request_status_payload(db, sync_request=row))


__all__ = ["router"]
