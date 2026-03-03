from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.session import get_db
from app.modules.users.schemas import (
    UserResponse,
    UserUpdateRequest,
)
from app.modules.users.service import (
    get_registered_user,
    update_current_user,
    user_not_initialized_detail,
)

router = APIRouter(prefix="/v2/users", tags=["users"], dependencies=[Depends(require_public_api_key)])


@router.get("/me", response_model=UserResponse)
def get_user(db: Session = Depends(get_db)) -> UserResponse:
    user = get_registered_user(db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=user_not_initialized_detail())
    return _to_user_response(user)


@router.patch("/me", response_model=UserResponse)
def patch_user(payload: UserUpdateRequest, db: Session = Depends(get_db)) -> UserResponse:
    user = get_registered_user(db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=user_not_initialized_detail())
    if "notify_email" in payload.model_fields_set and payload.notify_email is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="notify_email cannot be cleared")

    try:
        updated = update_current_user(
            db,
            user=user,
            email=payload.email,
            notify_email=payload.notify_email,
            calendar_delay_seconds=payload.calendar_delay_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_user_response(updated)


def _to_user_response(user) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        notify_email=user.notify_email,
        calendar_delay_seconds=user.calendar_delay_seconds,
        created_at=user.created_at,
    )
