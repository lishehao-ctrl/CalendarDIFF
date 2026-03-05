from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models.input import IngestTriggerType
from app.db.session import get_db
from app.modules.input_control_plane.router_common import require_owned_source_or_404, require_registered_user_or_409
from app.modules.input_control_plane.schemas import (
    SyncRequestCreateRequest,
    SyncRequestCreateResponse,
    SyncRequestStatusResponse,
)
from app.modules.input_control_plane.status_projection import build_sync_request_status_payload
from app.modules.input_control_plane.sync_requests_service import enqueue_sync_request_idempotent, get_sync_request_status

router = APIRouter()


@router.post("/sources/{source_id}/sync-requests", response_model=SyncRequestCreateResponse, status_code=status.HTTP_201_CREATED)
def create_sync_request(
    source_id: int,
    payload: SyncRequestCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> SyncRequestCreateResponse:
    user = require_registered_user_or_409(db)
    source = require_owned_source_or_404(db=db, user_id=user.id, source_id=source_id)
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
) -> SyncRequestStatusResponse:
    user = require_registered_user_or_409(db)
    row = get_sync_request_status(db, request_id=request_id)
    if row is None or row.source.user_id != user.id:
        raise HTTPException(status_code=404, detail="Sync request not found")
    return SyncRequestStatusResponse.model_validate(build_sync_request_status_payload(db, sync_request=row))


__all__ = ["router"]
