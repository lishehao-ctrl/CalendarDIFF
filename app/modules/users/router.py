from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.models.shared import User
from app.db.session import get_db
from app.modules.auth.deps import get_authenticated_user_or_401
from app.modules.users.schemas import (
    UserResponse,
    UserUpdateRequest,
)
from app.modules.users.service import update_current_user

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_public_api_key)])


@router.get("/me", response_model=UserResponse)
def get_user(user: User = Depends(get_authenticated_user_or_401)) -> UserResponse:
    return _to_user_response(user)


@router.patch("/me", response_model=UserResponse)
def patch_user(
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> UserResponse:
    if "notify_email" in payload.model_fields_set and payload.notify_email is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="notify_email cannot be cleared")

    try:
        updated = update_current_user(
            db,
            user=user,
            email=payload.email,
            notify_email=payload.notify_email,
            timezone_name=payload.timezone_name,
            calendar_delay_seconds=payload.calendar_delay_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_user_response(updated)


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        notify_email=user.notify_email,
        timezone_name=user.timezone_name,
        calendar_delay_seconds=user.calendar_delay_seconds,
        created_at=user.created_at,
    )
