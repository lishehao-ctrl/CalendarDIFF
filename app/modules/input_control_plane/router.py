from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.logging import sanitize_log_message
from app.core.security import require_public_api_key
from app.db.models import IngestTriggerType
from app.db.session import get_db
from app.modules.input_control_plane.schemas import (
    InputSourceCreateRequest,
    InputSourcePatchRequest,
    InputSourceResponse,
    OAuthCallbackResponse,
    OAuthSessionCreateRequest,
    OAuthSessionCreateResponse,
    SyncRequestCreateRequest,
    SyncRequestCreateResponse,
    SyncRequestStatusResponse,
    WebhookEnqueueResponse,
)
from app.modules.input_control_plane.service import (
    build_gmail_oauth_start_for_source,
    build_sync_request_status_payload,
    create_input_source,
    enqueue_sync_request_idempotent,
    get_input_source,
    get_sync_request_status,
    handle_gmail_oauth_callback,
    list_input_sources,
    serialize_source,
    soft_delete_input_source,
    update_input_source,
)
from app.modules.users.service import get_registered_user

router = APIRouter(prefix="/v2", tags=["input-control-plane"], dependencies=[Depends(require_public_api_key)])
public_router = APIRouter(prefix="/v2", tags=["input-control-plane-public"])


@router.post("/input-sources", response_model=InputSourceResponse, status_code=status.HTTP_201_CREATED)
def create_source(
    payload: InputSourceCreateRequest,
    db: Session = Depends(get_db),
) -> InputSourceResponse:
    user = _require_registered_user_or_409(db)
    try:
        source = create_input_source(db, user=user, payload=payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=sanitize_log_message(str(exc))) from exc
    return InputSourceResponse.model_validate(serialize_source(source))


@router.get("/input-sources", response_model=list[InputSourceResponse])
def list_sources(
    db: Session = Depends(get_db),
) -> list[InputSourceResponse]:
    user = _require_registered_user_or_409(db)
    rows = list_input_sources(db, user_id=user.id)
    return [InputSourceResponse.model_validate(serialize_source(row)) for row in rows]


@router.patch("/input-sources/{source_id}", response_model=InputSourceResponse)
def patch_source(
    source_id: int,
    payload: InputSourcePatchRequest,
    db: Session = Depends(get_db),
) -> InputSourceResponse:
    user = _require_registered_user_or_409(db)
    source = get_input_source(db, user_id=user.id, source_id=source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Input source not found")
    try:
        updated = update_input_source(db, source=source, payload=payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=sanitize_log_message(str(exc))) from exc
    return InputSourceResponse.model_validate(serialize_source(updated))


@router.delete("/input-sources/{source_id}", status_code=status.HTTP_200_OK)
def delete_source(
    source_id: int,
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    user = _require_registered_user_or_409(db)
    source = get_input_source(db, user_id=user.id, source_id=source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Input source not found")
    soft_delete_input_source(db, source=source)
    return {"deleted": True}


@router.post("/sync-requests", response_model=SyncRequestCreateResponse, status_code=status.HTTP_201_CREATED)
def create_sync_request(
    payload: SyncRequestCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> SyncRequestCreateResponse:
    user = _require_registered_user_or_409(db)
    source = get_input_source(db, user_id=user.id, source_id=payload.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Input source not found")
    if not source.is_active:
        raise HTTPException(
            status_code=409,
            detail={"code": "source_inactive", "message": "source is inactive and cannot be synced"},
        )
    applied_idempotency_key = idempotency_key or f"manual:{payload.source_id}:{uuid4().hex}"
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
    user = _require_registered_user_or_409(db)
    row = get_sync_request_status(db, request_id=request_id)
    if row is None or row.source.user_id != user.id:
        raise HTTPException(status_code=404, detail="Sync request not found")
    return SyncRequestStatusResponse.model_validate(build_sync_request_status_payload(db, sync_request=row))


@router.post("/oauth-sessions", response_model=OAuthSessionCreateResponse, status_code=status.HTTP_201_CREATED)
def create_oauth_session(
    payload: OAuthSessionCreateRequest,
    db: Session = Depends(get_db),
) -> OAuthSessionCreateResponse:
    user = _require_registered_user_or_409(db)
    source = get_input_source(db, user_id=user.id, source_id=payload.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Input source not found")
    provider = payload.provider.strip().lower()
    if provider != "gmail" or source.provider != "gmail":
        raise HTTPException(status_code=422, detail="Only gmail oauth is supported in current connector runtime")
    try:
        authorization_url, expires_at = build_gmail_oauth_start_for_source(db, source=source)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=sanitize_log_message(str(exc))) from exc
    return OAuthSessionCreateResponse(
        source_id=source.id,
        provider=provider,
        authorization_url=authorization_url,
        expires_at=expires_at,
    )


@public_router.get("/oauth-callbacks/{provider}", include_in_schema=False)
def oauth_callback(
    provider: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> OAuthCallbackResponse:
    normalized_provider = provider.strip().lower()
    if error:
        return OAuthCallbackResponse(
            provider=normalized_provider,
            status="error",
            message=sanitize_log_message(error),
        )
    if not code or not state:
        return OAuthCallbackResponse(
            provider=normalized_provider,
            status="error",
            message="oauth callback missing code/state",
        )
    if normalized_provider != "gmail":
        return OAuthCallbackResponse(
            provider=normalized_provider,
            status="error",
            message="unsupported oauth provider",
        )
    try:
        source, sync_request = handle_gmail_oauth_callback(db, code=code, state=state)
    except Exception as exc:
        return OAuthCallbackResponse(
            provider=normalized_provider,
            status="error",
            message=sanitize_log_message(str(exc)),
        )

    return OAuthCallbackResponse(
        provider=normalized_provider,
        status="success",
        source_id=source.id,
        request_id=sync_request.request_id,
        sync_request_status=sync_request.status.value,  # type: ignore[arg-type]
        message="oauth callback processed",
    )


@router.post("/webhook-events/{source_id}/{provider}", response_model=WebhookEnqueueResponse)
async def webhook_ingest(
    request: Request,
    source_id: int,
    provider: str,
    db: Session = Depends(get_db),
    x_event_id: str | None = Header(default=None, alias="X-Event-Id"),
) -> WebhookEnqueueResponse:
    user = get_registered_user(db)
    if user is None:
        raise HTTPException(status_code=409, detail={"code": "user_not_initialized", "message": "user not initialized"})

    source = get_input_source(db, user_id=user.id, source_id=source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Input source not found")

    normalized_provider = provider.strip().lower()
    if source.provider != normalized_provider:
        raise HTTPException(status_code=422, detail="provider mismatch")

    body = await request.body()
    event_id = x_event_id or hashlib.sha256(body).hexdigest()
    metadata: dict[str, object] = {
        "provider": normalized_provider,
        "event_id": event_id,
    }
    try:
        payload_json = json.loads(body.decode("utf-8")) if body else {}
        if isinstance(payload_json, dict):
            metadata["payload"] = payload_json
    except Exception:
        metadata["payload_raw"] = body.decode("utf-8", errors="replace")

    row = enqueue_sync_request_idempotent(
        db,
        source=source,
        trigger_type=IngestTriggerType.WEBHOOK,
        idempotency_key=f"webhook:{source.id}:{event_id}",
        metadata=metadata,
        trace_id=event_id,
    )
    return WebhookEnqueueResponse(request_id=row.request_id, status=row.status.value)


def _require_registered_user_or_409(db: Session):
    user = get_registered_user(db)
    if user is None:
        raise HTTPException(status_code=409, detail={"code": "user_not_initialized", "message": "user not initialized"})
    return user
