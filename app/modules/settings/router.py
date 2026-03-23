from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.models.shared import User
from app.db.session import get_db
from app.modules.auth.deps import get_authenticated_user_or_401
from app.modules.common.api_errors import api_error_detail
from app.modules.settings.mcp_tokens_service import (
    McpAccessTokenNotFoundError,
    create_mcp_access_token,
    list_mcp_access_tokens,
    revoke_mcp_access_token,
)
from app.modules.settings.schemas import (
    McpAccessTokenCreateRequest,
    McpAccessTokenCreateResponse,
    McpAccessTokenResponse,
    UserResponse,
    UserUpdateRequest,
)
from app.modules.settings.serializers import to_user_response
from app.modules.settings.service import update_current_user

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_public_api_key)])


@router.get("/profile", response_model=UserResponse)
def get_profile(user: User = Depends(get_authenticated_user_or_401)) -> UserResponse:
    return to_user_response(user)


@router.patch("/profile", response_model=UserResponse)
def patch_profile(
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> UserResponse:
    if "notify_email" in payload.model_fields_set and payload.notify_email is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=api_error_detail(
                code="notify_email_cannot_be_cleared",
                message="notify_email cannot be cleared",
                message_code="settings.notify_email_cannot_be_cleared",
            ),
        )
    try:
        updated = update_current_user(
            db,
            user=user,
            email=payload.email,
            notify_email=payload.notify_email,
            timezone_name=payload.timezone_name,
            timezone_source=payload.timezone_source,
            language_code=payload.language_code,
            calendar_delay_seconds=payload.calendar_delay_seconds,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=api_error_detail(
                code="settings_invalid_input",
                message=str(exc),
                message_code="settings.validation_error",
            ),
        ) from exc
    return to_user_response(updated)


@router.get("/mcp-tokens", response_model=list[McpAccessTokenResponse])
def get_mcp_tokens(
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> list[McpAccessTokenResponse]:
    rows = list_mcp_access_tokens(db, user_id=user.id)
    return [
        McpAccessTokenResponse(
            token_id=row.token_id,
            label=row.label,
            scopes=row.scopes_json or [],
            last_used_at=row.last_used_at,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/mcp-tokens", response_model=McpAccessTokenCreateResponse, status_code=status.HTTP_201_CREATED)
def post_mcp_token(
    payload: McpAccessTokenCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> McpAccessTokenCreateResponse:
    row, token = create_mcp_access_token(
        db,
        user=user,
        label=payload.label,
        expires_in_days=payload.expires_in_days,
    )
    return McpAccessTokenCreateResponse(
        token_id=row.token_id,
        token=token,
        label=row.label,
        scopes=row.scopes_json or [],
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
    )


@router.delete("/mcp-tokens/{token_id}", response_model=McpAccessTokenResponse)
def delete_mcp_token(
    token_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> McpAccessTokenResponse:
    try:
        row = revoke_mcp_access_token(db, user_id=user.id, token_id=token_id)
    except McpAccessTokenNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=api_error_detail(
                code="settings.mcp_token_not_found",
                message=str(exc),
                message_code="settings.mcp_token_not_found",
            ),
        ) from exc
    return McpAccessTokenResponse(
        token_id=row.token_id,
        label=row.label,
        scopes=row.scopes_json or [],
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
    )


__all__ = ["router"]
