from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models.shared import User
from app.modules.users.service import get_first_active_input_source


class OnboardingRegisterError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class OnboardingStatus:
    stage: str
    message: str
    registered_user_id: int | None
    first_source_id: int | None
    last_error: str | None


@dataclass(frozen=True)
class OnboardingRegisterResult:
    user_id: int
    stage: str
    first_source_id: int | None


def get_onboarding_status_for_user(db: Session, *, user: User) -> OnboardingStatus:
    first_source = get_first_active_input_source(db, user_id=user.id)

    if first_source is None:
        return OnboardingStatus(
            stage="needs_source_connection",
            message="Connect at least one active input source.",
            registered_user_id=user.id,
            first_source_id=None,
            last_error=None,
        )

    return OnboardingStatus(
        stage="ready",
        message="Onboarding complete.",
        registered_user_id=user.id,
        first_source_id=first_source.id,
        last_error=first_source.last_error_message,
    )


def get_onboarding_status(db: Session, *, user: User) -> OnboardingStatus:
    return get_onboarding_status_for_user(db, user=user)


def register_onboarding(
    db: Session,
    *,
    user: User,
    notify_email: str,
) -> OnboardingRegisterResult:
    normalized = notify_email.strip().lower()
    if normalized != (user.notify_email or "").strip().lower():
        raise OnboardingRegisterError("notify_email is managed by auth register flow", status_code=422)

    status = get_onboarding_status_for_user(db, user=user)
    return OnboardingRegisterResult(
        user_id=user.id,
        stage=status.stage,
        first_source_id=status.first_source_id,
    )
