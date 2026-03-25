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
from app.modules.channels.service import (
    ChannelAccountNotFoundError,
    create_channel_account,
    list_channel_accounts,
    list_channel_deliveries,
    revoke_channel_account,
)
from app.modules.agents.mcp_audit_service import list_mcp_tool_invocations
from app.modules.settings.schemas import (
    ChannelAccountCreateRequest,
    ChannelAccountResponse,
    ChannelDeliveryResponse,
    McpAccessTokenCreateRequest,
    McpAccessTokenCreateResponse,
    McpAccessTokenResponse,
    McpToolInvocationResponse,
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
    try:
        updated = update_current_user(
            db,
            user=user,
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


@router.get("/channel-accounts", response_model=list[ChannelAccountResponse])
def get_channel_accounts(
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> list[ChannelAccountResponse]:
    rows = list_channel_accounts(db, user_id=user.id)
    return [
        ChannelAccountResponse(
            id=row.id,
            channel_type=row.channel_type.value,
            account_label=row.account_label,
            external_user_id=row.external_user_id,
            external_workspace_id=row.external_workspace_id,
            status=row.status.value,
            verification_status=row.verification_status.value,
            last_seen_at=row.last_seen_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.post("/channel-accounts", response_model=ChannelAccountResponse, status_code=status.HTTP_201_CREATED)
def post_channel_account(
    payload: ChannelAccountCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> ChannelAccountResponse:
    row = create_channel_account(
        db,
        user=user,
        channel_type=payload.channel_type,
        account_label=payload.account_label,
        external_user_id=payload.external_user_id,
        external_workspace_id=payload.external_workspace_id,
    )
    return ChannelAccountResponse(
        id=row.id,
        channel_type=row.channel_type.value,
        account_label=row.account_label,
        external_user_id=row.external_user_id,
        external_workspace_id=row.external_workspace_id,
        status=row.status.value,
        verification_status=row.verification_status.value,
        last_seen_at=row.last_seen_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.delete("/channel-accounts/{account_id}", response_model=ChannelAccountResponse)
def delete_channel_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> ChannelAccountResponse:
    try:
        row = revoke_channel_account(db, user_id=user.id, account_id=account_id)
    except ChannelAccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=api_error_detail(
                code="settings.channel_account_not_found",
                message=str(exc),
                message_code="settings.channel_account_not_found",
            ),
        ) from exc
    return ChannelAccountResponse(
        id=row.id,
        channel_type=row.channel_type.value,
        account_label=row.account_label,
        external_user_id=row.external_user_id,
        external_workspace_id=row.external_workspace_id,
        status=row.status.value,
        verification_status=row.verification_status.value,
        last_seen_at=row.last_seen_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/channel-deliveries", response_model=list[ChannelDeliveryResponse])
def get_channel_deliveries(
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> list[ChannelDeliveryResponse]:
    rows = list_channel_deliveries(db, user_id=user.id, limit=max(1, min(int(limit), 100)))
    return [
        ChannelDeliveryResponse(
            delivery_id=row.delivery_id,
            channel_account_id=row.channel_account_id,
            proposal_id=row.proposal_id,
            ticket_id=row.ticket_id,
            delivery_kind=row.delivery_kind,
            status=row.status.value,
            attempt_count=int(row.attempt_count or 0),
            summary_code=row.summary_code,
            detail_code=row.detail_code,
            cta_code=row.cta_code,
            payload=row.payload_json or {},
            origin_kind=row.origin_kind,
            origin_label=row.origin_label,
            external_message_id=row.external_message_id,
            sent_at=row.sent_at,
            acknowledged_at=row.acknowledged_at,
            failed_at=row.failed_at,
            error_text=row.error_text,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.get("/mcp-invocations", response_model=list[McpToolInvocationResponse])
def get_mcp_invocations(
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> list[McpToolInvocationResponse]:
    rows = list_mcp_tool_invocations(db, user_id=user.id, limit=max(1, min(int(limit), 100)))
    return [
        McpToolInvocationResponse(
            invocation_id=row.invocation_id,
            transport_request_id=row.transport_request_id,
            tool_name=row.tool_name,
            transport=row.transport,
            auth_mode=row.auth_mode,
            status=row.status.value,
            proposal_id=row.proposal_id,
            ticket_id=row.ticket_id,
            target_kind=(row.output_summary_json or {}).get("target_kind"),
            target_id=(row.output_summary_json or {}).get("target_id"),
            summary_code=(row.output_summary_json or {}).get("summary_code"),
            output_summary=row.output_summary_json or {},
            error_text=row.error_text,
            created_at=row.created_at,
            completed_at=row.completed_at,
        )
        for row in rows
    ]


__all__ = ["router"]
