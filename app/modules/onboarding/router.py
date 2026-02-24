from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_api_key
from app.db.session import get_db
from app.modules.onboarding.schemas import (
    OnboardingRegisterRequest,
    OnboardingRegisterResponse,
    OnboardingStatusResponse,
)
from app.modules.onboarding.service import OnboardingRegisterError, get_onboarding_status, register_onboarding

router = APIRouter(prefix="/v1/onboarding", tags=["onboarding"], dependencies=[Depends(require_api_key)])


@router.get("/status", response_model=OnboardingStatusResponse)
def get_status(db: Session = Depends(get_db)) -> OnboardingStatusResponse:
    status_payload = get_onboarding_status(db)
    return OnboardingStatusResponse(
        stage=status_payload.stage,  # type: ignore[arg-type]
        message=status_payload.message,
        registered_user_id=status_payload.registered_user_id,
        first_input_id=status_payload.first_input_id,
        last_error=status_payload.last_error,
    )


@router.post("/register", response_model=OnboardingRegisterResponse)
def post_register(payload: OnboardingRegisterRequest, db: Session = Depends(get_db)) -> OnboardingRegisterResponse:
    try:
        result = register_onboarding(
            db,
            notify_email=payload.notify_email,
            term_code=payload.term.code,
            term_label=payload.term.label,
            term_starts_on=payload.term.starts_on,
            term_ends_on=payload.term.ends_on,
            ics_url=str(payload.ics.url),
        )
    except OnboardingRegisterError as exc:
        status_code = exc.status_code if exc.status_code in {409, 422, 502} else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    return OnboardingRegisterResponse(
        status="ready",
        user_id=result.user_id,
        term_id=result.term_id,
        input_id=result.input_id,
        is_baseline_sync=result.is_baseline_sync,
        changes_created=result.changes_created,
    )
