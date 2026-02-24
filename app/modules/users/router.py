from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import require_api_key
from app.db.session import get_db
from app.modules.users.schemas import (
    UserResponse,
    UserTermCreateRequest,
    UserTermResponse,
    UserTermUpdateRequest,
    UserUpdateRequest,
)
from app.modules.users.service import (
    create_user_term,
    get_current_user,
    get_user_term_by_id,
    list_user_terms,
    update_current_user,
    update_user_term,
)

router = APIRouter(prefix="/v1/user", tags=["user"], dependencies=[Depends(require_api_key)])


@router.get("", response_model=UserResponse)
def get_user(db: Session = Depends(get_db)) -> UserResponse:
    user = get_current_user(db)
    return UserResponse(
        id=user.id,
        email=user.email,
        notify_email=user.notify_email,
        calendar_delay_seconds=user.calendar_delay_seconds,
        created_at=user.created_at,
    )


@router.patch("", response_model=UserResponse)
def patch_user(payload: UserUpdateRequest, db: Session = Depends(get_db)) -> UserResponse:
    user = get_current_user(db)
    updated = update_current_user(
        db,
        user=user,
        email=payload.email,
        notify_email=payload.notify_email,
        calendar_delay_seconds=payload.calendar_delay_seconds,
    )
    return UserResponse(
        id=updated.id,
        email=updated.email,
        notify_email=updated.notify_email,
        calendar_delay_seconds=updated.calendar_delay_seconds,
        created_at=updated.created_at,
    )


@router.get("/terms", response_model=list[UserTermResponse])
def get_terms(db: Session = Depends(get_db)) -> list[UserTermResponse]:
    user = get_current_user(db)
    rows = list_user_terms(db, user_id=user.id)
    return [_to_term_response(term) for term in rows]


@router.post("/terms", response_model=UserTermResponse, status_code=status.HTTP_201_CREATED)
def post_term(payload: UserTermCreateRequest, db: Session = Depends(get_db)) -> UserTermResponse:
    user = get_current_user(db)
    try:
        term = create_user_term(
            db,
            user_id=user.id,
            code=payload.code,
            label=payload.label,
            starts_on=payload.starts_on,
            ends_on=payload.ends_on,
            is_active=payload.is_active,
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Term code already exists for this user") from exc
    return _to_term_response(term)


@router.patch("/terms/{term_id}", response_model=UserTermResponse)
def patch_term(term_id: int, payload: UserTermUpdateRequest, db: Session = Depends(get_db)) -> UserTermResponse:
    user = get_current_user(db)
    term = get_user_term_by_id(db, user_id=user.id, term_id=term_id)
    if term is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Term not found")

    try:
        updated = update_user_term(
            db,
            term=term,
            code=payload.code,
            label=payload.label,
            starts_on=payload.starts_on,
            ends_on=payload.ends_on,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Term code already exists for this user") from exc

    return _to_term_response(updated)


def _to_term_response(term) -> UserTermResponse:
    return UserTermResponse(
        id=term.id,
        user_id=term.user_id,
        code=term.code,
        label=term.label,
        starts_on=term.starts_on,
        ends_on=term.ends_on,
        is_active=term.is_active,
        created_at=term.created_at,
        updated_at=term.updated_at,
    )
