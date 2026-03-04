from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.session import get_db
from app.modules.onboarding.schemas import (
    OnboardingRegisterRequest,
    OnboardingRegisterResponse,
    OnboardingStatusResponse,
)
from app.modules.onboarding.service import OnboardingRegisterError, get_onboarding_status, register_onboarding

router = APIRouter(prefix="/onboarding", tags=["onboarding"], dependencies=[Depends(require_public_api_key)])


@router.get("/status", response_model=OnboardingStatusResponse)
def get_status(db: Session = Depends(get_db)) -> OnboardingStatusResponse:
    status_payload = get_onboarding_status(db)
    return OnboardingStatusResponse(
        stage=status_payload.stage,  # type: ignore[arg-type]
        message=status_payload.message,
        registered_user_id=status_payload.registered_user_id,
        first_source_id=status_payload.first_source_id,
        last_error=status_payload.last_error,
    )


@router.post("/registrations", response_model=OnboardingRegisterResponse)
def create_registration(payload: OnboardingRegisterRequest, db: Session = Depends(get_db)) -> OnboardingRegisterResponse:
    try:
        result = register_onboarding(
            db,
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
