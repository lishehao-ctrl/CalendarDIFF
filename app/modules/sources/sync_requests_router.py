from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.models.input import IngestTriggerType
from app.db.models.shared import User
from app.db.session import get_db
from app.modules.auth.deps import get_authenticated_user_or_401
from app.modules.common.api_errors import api_error_detail
from app.modules.common.request_rate_limit import enforce_user_mutation_rate_limit
from app.modules.common.source_monitoring_window import parse_source_monitoring_window, source_timezone_name
from app.modules.sources.router_common import require_owned_source_or_404
from app.modules.sources.schemas import (
    SyncRequestLlmInvocationsResponse,
    SyncRequestCreateRequest,
    SyncRequestCreateResponse,
    SyncRequestStatusResponse,
)
from app.modules.sources.llm_invocations_service import list_sync_request_llm_invocations
from app.modules.sources.source_monitoring_window_rebind import has_pending_monitoring_window_update
from app.modules.sources.status_projection import build_sync_request_status_payload
from app.modules.sources.sync_requests_service import enqueue_sync_request_idempotent, get_sync_request_status

router = APIRouter()


@router.post("/sources/{source_id}/sync-requests", response_model=SyncRequestCreateResponse, status_code=status.HTTP_201_CREATED)
def create_sync_request(
    source_id: int,
    payload: SyncRequestCreateRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> SyncRequestCreateResponse:
    enforce_user_mutation_rate_limit(request, user_id=user.id)
    source = require_owned_source_or_404(db=db, user_id=user.id, source_id=source_id)
    if has_pending_monitoring_window_update(source):
        raise HTTPException(
            status_code=409,
            detail=api_error_detail(
                code="source_monitoring_window_update_pending",
                message="source monitoring window update is pending",
                message_code="sources.sync.monitoring_window_update_pending",
            ),
        )
    term_window = parse_source_monitoring_window(source, required=False)
    now = datetime.now(timezone.utc)
    if term_window is not None and not term_window.has_started(now=now, timezone_name=source_timezone_name(source)):
        raise HTTPException(
            status_code=409,
            detail=api_error_detail(
                code="source_monitoring_not_started",
                message="source monitoring has not started yet",
                message_code="sources.sync.monitoring_not_started",
            ),
        )
    if not source.is_active:
        raise HTTPException(
            status_code=409,
            detail=api_error_detail(
                code="source_inactive",
                message="source is inactive and cannot be synced",
                message_code="sources.sync.source_inactive",
            ),
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
        raise HTTPException(
            status_code=404,
            detail=api_error_detail(
                code="sync_request_not_found",
                message="Sync request not found",
                message_code="sources.sync.request_not_found",
            ),
        )
    return SyncRequestStatusResponse.model_validate(build_sync_request_status_payload(db, sync_request=row))


@router.get("/sync-requests/{request_id}/llm-invocations", response_model=SyncRequestLlmInvocationsResponse)
def get_sync_request_llm_invocations(
    request_id: str,
    limit: int = 200,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> SyncRequestLlmInvocationsResponse:
    row = get_sync_request_status(db, request_id=request_id)
    if row is None or row.source.user_id != user.id:
        raise HTTPException(
            status_code=404,
            detail=api_error_detail(
                code="sync_request_not_found",
                message="Sync request not found",
                message_code="sources.sync.request_not_found",
            ),
        )
    return SyncRequestLlmInvocationsResponse.model_validate(
        list_sync_request_llm_invocations(
            db,
            request_id=request_id,
            limit=max(min(int(limit), 500), 1),
        )
    )


__all__ = ["router"]
