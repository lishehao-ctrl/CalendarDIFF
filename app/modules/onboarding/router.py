from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.logging import sanitize_log_message
from app.core.security import require_public_api_key
from app.db.models.shared import User
from app.db.session import get_db
from app.modules.auth.deps import get_authenticated_user_or_401
from app.modules.onboarding.schemas import (
    OnboardingCanvasIcsRequest,
    OnboardingGmailOAuthRequest,
    OnboardingGmailSkipRequest,
    OnboardingOAuthSessionCreateResponse,
    OnboardingRegisterRequest,
    OnboardingRegisterResponse,
    OnboardingSourceResponse,
    OnboardingStatusResponse,
    OnboardingTermBindingRequest,
    OnboardingTermBindingResponse,
    SourceHealthSummaryResponse,
)
from app.modules.onboarding.service import (
    OnboardingRegisterError,
    apply_onboarding_term_binding,
    get_onboarding_status,
    register_onboarding,
    skip_onboarding_gmail,
    start_onboarding_gmail_oauth,
    upsert_onboarding_canvas_ics,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"], dependencies=[Depends(require_public_api_key)])


@router.get("/status", response_model=OnboardingStatusResponse)
def get_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> OnboardingStatusResponse:
    status_payload = get_onboarding_status(db, user=user)
    return _serialize_onboarding_status(status_payload)


@router.post("/registrations", response_model=OnboardingRegisterResponse)
def create_registration(
    payload: OnboardingRegisterRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> OnboardingRegisterResponse:
    try:
        result = register_onboarding(
            db,
            user=user,
            notify_email=payload.notify_email,
        )
    except OnboardingRegisterError as exc:
        status_code = exc.status_code if exc.status_code in {409, 422} else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    return OnboardingRegisterResponse(
        status="accepted",
        user_id=result.user_id,
        stage=result.stage,  # type: ignore[arg-type]
        first_source_id=result.first_source_id,
    )


@router.post("/canvas-ics", response_model=OnboardingStatusResponse)
def upsert_canvas_ics(
    payload: OnboardingCanvasIcsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> OnboardingStatusResponse:
    try:
        status_payload = upsert_onboarding_canvas_ics(db, user=user, url=payload.url)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=sanitize_log_message(str(exc))) from exc
    return _serialize_onboarding_status(status_payload)


@router.post("/gmail/oauth-sessions", response_model=OnboardingOAuthSessionCreateResponse, status_code=status.HTTP_201_CREATED)
def create_onboarding_gmail_oauth_session(
    payload: OnboardingGmailOAuthRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> OnboardingOAuthSessionCreateResponse:
    try:
        source, authorization_url, expires_at = start_onboarding_gmail_oauth(
            db,
            user=user,
            label_id=payload.label_id,
            return_to=payload.return_to,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=sanitize_log_message(str(exc))) from exc
    return OnboardingOAuthSessionCreateResponse(
        source_id=source.id,
        provider="gmail",
        authorization_url=authorization_url,
        expires_at=expires_at,
    )


@router.post("/gmail-skip", response_model=OnboardingStatusResponse)
def skip_gmail(
    payload: OnboardingGmailSkipRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> OnboardingStatusResponse:
    del payload
    status_payload = skip_onboarding_gmail(db, user=user)
    return _serialize_onboarding_status(status_payload)


@router.post("/term-binding", response_model=OnboardingStatusResponse)
def save_term_binding(
    payload: OnboardingTermBindingRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> OnboardingStatusResponse:
    try:
        status_payload = apply_onboarding_term_binding(
            db,
            user=user,
            term_key=payload.term_key,
            term_from=payload.term_from.isoformat(),
            term_to=payload.term_to.isoformat(),
        )
    except OnboardingRegisterError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=sanitize_log_message(str(exc))) from exc
    return _serialize_onboarding_status(status_payload)


def _serialize_onboarding_status(status_payload) -> OnboardingStatusResponse:
    return OnboardingStatusResponse(
        stage=status_payload.stage,  # type: ignore[arg-type]
        message=status_payload.message,
        registered_user_id=status_payload.registered_user_id,
        first_source_id=status_payload.first_source_id,
        source_health=SourceHealthSummaryResponse(
            status=status_payload.source_health.status,  # type: ignore[arg-type]
            message=status_payload.source_health.message,
            affected_source_id=status_payload.source_health.affected_source_id,
            affected_provider=status_payload.source_health.affected_provider,
        ),
        canvas_source=_serialize_onboarding_source(status_payload.canvas_source),
        gmail_source=_serialize_onboarding_source(status_payload.gmail_source),
        gmail_skipped=status_payload.gmail_skipped,
        term_binding=_serialize_term_binding(status_payload.term_binding),
    )


def _serialize_onboarding_source(source_payload) -> OnboardingSourceResponse | None:
    if source_payload is None:
        return None
    return OnboardingSourceResponse(
        source_id=source_payload.source_id,
        provider=source_payload.provider,  # type: ignore[arg-type]
        connected=source_payload.connected,
        has_term_binding=source_payload.has_term_binding,
        runtime_state=source_payload.runtime_state,  # type: ignore[arg-type]
        oauth_account_email=source_payload.oauth_account_email,
        term_binding=_serialize_term_binding(source_payload.term_binding),
    )


def _serialize_term_binding(term_binding) -> OnboardingTermBindingResponse | None:
    if term_binding is None:
        return None
    return OnboardingTermBindingResponse(
        term_key=term_binding.term_key,
        term_from=term_binding.term_from,
        term_to=term_binding.term_to,
    )
