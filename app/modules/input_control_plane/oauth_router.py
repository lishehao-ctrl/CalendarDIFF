from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.logging import sanitize_log_message
from app.core.oauth_config import build_oauth_runtime_config
from app.db.models.shared import User
from app.db.session import get_db
from app.modules.auth.deps import get_authenticated_user_or_401
from app.modules.input_control_plane.oauth_service import (
    build_gmail_oauth_start_for_source,
    build_oauth_browser_callback_redirect_url,
    handle_gmail_oauth_callback,
)
from app.modules.input_control_plane.router_common import require_owned_source_or_404
from app.modules.input_control_plane.schemas import (
    OAuthCallbackResponse,
    OAuthSessionCreateRequest,
    OAuthSessionCreateResponse,
)

_OAUTH_RUNTIME = build_oauth_runtime_config()

router = APIRouter()
public_router = APIRouter(tags=["input-control-plane-public"])


@router.post(
    _OAUTH_RUNTIME.oauth_session_route_path,
    response_model=OAuthSessionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_oauth_session(
    source_id: int,
    payload: OAuthSessionCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> OAuthSessionCreateResponse:
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


@public_router.get(_OAUTH_RUNTIME.callback_route_path, include_in_schema=False, response_model=None)
def oauth_callback(
    provider: str,
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    format: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    normalized_provider = provider.strip().lower()

    if error:
        payload = OAuthCallbackResponse(
            provider=normalized_provider,
            status="error",
            message=sanitize_log_message(error),
        )
        return _finalize_oauth_callback_response(request=request, format=format, payload=payload)

    if not code or not state:
        payload = OAuthCallbackResponse(
            provider=normalized_provider,
            status="error",
            message="oauth callback missing code/state",
        )
        return _finalize_oauth_callback_response(request=request, format=format, payload=payload)

    if normalized_provider != "gmail":
        payload = OAuthCallbackResponse(
            provider=normalized_provider,
            status="error",
            message="unsupported oauth provider",
        )
        return _finalize_oauth_callback_response(request=request, format=format, payload=payload)

    try:
        source, sync_request = handle_gmail_oauth_callback(db, code=code, state=state)
        payload = OAuthCallbackResponse(
            provider=normalized_provider,
            status="success",
            source_id=source.id,
            request_id=sync_request.request_id,
            sync_request_status=sync_request.status.value,  # type: ignore[arg-type]
            message="oauth callback processed",
        )
    except Exception as exc:
        payload = OAuthCallbackResponse(
            provider=normalized_provider,
            status="error",
            message=sanitize_log_message(str(exc)),
        )

    return _finalize_oauth_callback_response(request=request, format=format, payload=payload)


def _finalize_oauth_callback_response(
    *,
    request: Request,
    format: str | None,
    payload: OAuthCallbackResponse,
):
    if _prefers_json_response(request=request, format=format):
        return payload

    try:
        redirect_url = build_oauth_browser_callback_redirect_url(
            provider=payload.provider,
            status=payload.status,
            source_id=payload.source_id,
            request_id=payload.request_id,
            message=payload.message,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=sanitize_log_message(str(exc))) from exc
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


def _prefers_json_response(*, request: Request, format: str | None) -> bool:
    if isinstance(format, str) and format.strip().lower() == "json":
        return True
    accept = request.headers.get("accept", "").lower()
    return "application/json" in accept and "text/html" not in accept


__all__ = ["public_router", "router"]
