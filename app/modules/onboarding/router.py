from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.logging import sanitize_log_message
from app.core.security import require_public_api_key
from app.db.models.shared import User
from app.db.session import get_db
from app.modules.auth.deps import get_authenticated_user_or_401
from app.modules.common.api_errors import api_error_detail
from app.modules.onboarding.schemas import (
    OnboardingCanvasIcsRequest,
    OnboardingGmailOAuthRequest,
    OnboardingGmailSkipRequest,
    OnboardingMonitoringWindowRequest,
    OnboardingMonitoringWindowResponse,
    OnboardingOAuthSessionCreateResponse,
    OnboardingRegisterRequest,
    OnboardingRegisterResponse,
    OnboardingSourceResponse,
    OnboardingStatusResponse,
    SourceHealthSummaryResponse,
)
from app.modules.onboarding.service import (
    OnboardingRegisterError,
    apply_onboarding_monitoring_window,
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
            email=payload.email,
        )
    except OnboardingRegisterError as exc:
        status_code = exc.status_code if exc.status_code in {409, 422} else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(
            status_code=status_code,
            detail=api_error_detail(
                code=exc.code,
                message=str(exc),
                message_code=exc.message_code,
                message_params=exc.message_params,
            ),
        ) from exc

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
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=api_error_detail(
                code="onboarding_canvas_ics_invalid",
                message=sanitize_log_message(str(exc)),
                message_code="onboarding.canvas_ics.validation_error",
            ),
        ) from exc
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
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=api_error_detail(
                code="onboarding_gmail_oauth_unavailable",
                message=sanitize_log_message(str(exc)),
                message_code="onboarding.gmail_oauth.unavailable",
            ),
        ) from exc
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


@router.post("/monitoring-window", response_model=OnboardingStatusResponse)
def save_monitoring_window(
    payload: OnboardingMonitoringWindowRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> OnboardingStatusResponse:
    try:
        status_payload = apply_onboarding_monitoring_window(
            db,
            user=user,
            monitor_since=payload.monitor_since.isoformat(),
        )
    except OnboardingRegisterError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=api_error_detail(
                code=exc.code,
                message=str(exc),
                message_code=exc.message_code,
                message_params=exc.message_params,
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=api_error_detail(
                code="onboarding_monitoring_window_invalid",
                message=sanitize_log_message(str(exc)),
                message_code="onboarding.monitoring_window.validation_error",
            ),
        ) from exc
    return _serialize_onboarding_status(status_payload)


def _serialize_onboarding_status(status_payload) -> OnboardingStatusResponse:
    return OnboardingStatusResponse(
        stage=status_payload.stage,  # type: ignore[arg-type]
        message=status_payload.message,
        message_code=status_payload.message_code,
        message_params=status_payload.message_params,
        registered_user_id=status_payload.registered_user_id,
        first_source_id=status_payload.first_source_id,
        source_health=SourceHealthSummaryResponse(
            status=status_payload.source_health.status,  # type: ignore[arg-type]
            message=status_payload.source_health.message,
            message_code=status_payload.source_health.message_code,
            message_params=status_payload.source_health.message_params,
            affected_source_id=status_payload.source_health.affected_source_id,
            affected_provider=status_payload.source_health.affected_provider,
        ),
        canvas_source=_serialize_onboarding_source(status_payload.canvas_source),
        gmail_source=_serialize_onboarding_source(status_payload.gmail_source),
        gmail_skipped=status_payload.gmail_skipped,
        monitoring_window=_serialize_monitoring_window(status_payload.monitoring_window),
    )


def _serialize_onboarding_source(source_payload) -> OnboardingSourceResponse | None:
    if source_payload is None:
        return None
    return OnboardingSourceResponse(
        source_id=source_payload.source_id,
        provider=source_payload.provider,  # type: ignore[arg-type]
        connected=source_payload.connected,
        has_monitoring_window=source_payload.has_monitoring_window,
        runtime_state=source_payload.runtime_state,  # type: ignore[arg-type]
        oauth_account_email=source_payload.oauth_account_email,
        monitoring_window=_serialize_monitoring_window(source_payload.monitoring_window),
    )


def _serialize_monitoring_window(monitoring_window) -> OnboardingMonitoringWindowResponse | None:
    if monitoring_window is None:
        return None
    return OnboardingMonitoringWindowResponse(
        monitor_since=monitoring_window.monitor_since,
    )
