from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.session import get_db
from app.modules.auth.deps import attach_session_cookie, clear_session_cookie, get_authenticated_user_or_401
from app.modules.auth.schemas import AuthLoginRequest, AuthLogoutResponse, AuthRegisterRequest, AuthSessionResponse, AuthSessionUserResponse
from app.modules.auth.service import AuthEmailExistsError, InvalidCredentialsError, login_user, register_user
from app.modules.onboarding.service import get_onboarding_status_for_user
from app.db.models.shared import User

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(require_public_api_key)])


@router.post("/register", response_model=AuthSessionResponse, status_code=status.HTTP_201_CREATED)
def register_auth(
    payload: AuthRegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthSessionResponse:
    try:
        user = register_user(
            db,
            notify_email=payload.notify_email,
            password=payload.password,
            timezone_name=payload.timezone_name,
        )
    except AuthEmailExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    attach_session_cookie(response, user=user, db=db)
    return AuthSessionResponse(user=_to_auth_session_user(db, user=user))


@router.post("/login", response_model=AuthSessionResponse)
def login_auth(
    payload: AuthLoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthSessionResponse:
    try:
        user = login_user(
            db,
            notify_email=payload.notify_email,
            password=payload.password,
            timezone_name=payload.timezone_name,
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    attach_session_cookie(response, user=user, db=db)
    return AuthSessionResponse(user=_to_auth_session_user(db, user=user))


@router.post("/logout", response_model=AuthLogoutResponse)
def logout_auth(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthLogoutResponse:
    clear_session_cookie(response, request=request, db=db)
    return AuthLogoutResponse(logged_out=True)


@router.get("/session", response_model=AuthSessionResponse)
def get_auth_session(
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> AuthSessionResponse:
    return AuthSessionResponse(user=_to_auth_session_user(db, user=user))


def _to_auth_session_user(db: Session, *, user: User) -> AuthSessionUserResponse:
    status_payload = get_onboarding_status_for_user(db, user=user)
    return AuthSessionUserResponse(
        id=user.id,
        notify_email=user.notify_email or "",
        timezone_name=user.timezone_name,
        timezone_source=user.timezone_source,
        created_at=user.created_at,
        onboarding_stage=status_payload.stage,  # type: ignore[arg-type]
        first_source_id=status_payload.first_source_id,
    )
