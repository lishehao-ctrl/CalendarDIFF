from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.logging import sanitize_log_message
from app.db.session import get_db
from app.modules.input_control_plane.oauth_service import (
    build_gmail_oauth_start_for_source,
    handle_gmail_oauth_callback,
)
from app.modules.input_control_plane.router_common import require_owned_source_or_404, require_registered_user_or_409
from app.modules.input_control_plane.schemas import (
    OAuthCallbackResponse,
    OAuthSessionCreateRequest,
    OAuthSessionCreateResponse,
)

router = APIRouter()
public_router = APIRouter(tags=["input-control-plane-public"])


@router.post("/sources/{source_id}/oauth-sessions", response_model=OAuthSessionCreateResponse, status_code=status.HTTP_201_CREATED)
def create_oauth_session(
    source_id: int,
    payload: OAuthSessionCreateRequest,
    db: Session = Depends(get_db),
) -> OAuthSessionCreateResponse:
    user = require_registered_user_or_409(db)
    source = require_owned_source_or_404(db=db, user_id=user.id, source_id=source_id)
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


@public_router.get("/oauth/callbacks/{provider}", include_in_schema=False)
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


__all__ = ["public_router", "router"]
