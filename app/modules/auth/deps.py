from __future__ import annotations

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.db.models.shared import User
from app.db.session import get_db
from app.modules.auth.service import (
    AUTH_SESSION_COOKIE_NAME,
    AuthenticationRequiredError,
    build_session_cookie_kwargs,
    create_user_session,
    delete_user_session,
    get_authenticated_user_from_request,
)
from app.modules.onboarding.service import get_onboarding_status_for_user


def get_authenticated_user_or_401(request: Request, db: Session = Depends(get_db)) -> User:
    try:
        return get_authenticated_user_from_request(db, request=request)
    except AuthenticationRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required") from exc


def get_onboarded_authenticated_user_or_409(
    user: User = Depends(get_authenticated_user_or_401),
    db: Session = Depends(get_db),
) -> User:
    if user.onboarding_completed_at is not None:
        return user
    status_payload = get_onboarding_status_for_user(db, user=user)
    if status_payload.stage != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "user_onboarding_incomplete", "message": status_payload.message},
        )
    return user


def attach_session_cookie(response: Response, *, user: User, db: Session) -> None:
    cookie_value = create_user_session(db, user=user)
    response.set_cookie(AUTH_SESSION_COOKIE_NAME, cookie_value, **build_session_cookie_kwargs())


def clear_session_cookie(response: Response, *, request: Request, db: Session) -> None:
    delete_user_session(db, cookie_value=request.cookies.get(AUTH_SESSION_COOKIE_NAME))
    response.delete_cookie(AUTH_SESSION_COOKIE_NAME, path="/")
