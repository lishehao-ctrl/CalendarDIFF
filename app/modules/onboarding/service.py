from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.modules.users.service import (
    create_or_initialize_user,
    get_first_active_input_source,
    get_registered_user,
)


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


def get_onboarding_status(db: Session) -> OnboardingStatus:
    user = get_registered_user(db)
    if user is None:
        return OnboardingStatus(
            stage="needs_user",
            message="Create user profile first with notify_email.",
            registered_user_id=None,
            first_source_id=None,
            last_error=None,
        )

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


def register_onboarding(
    db: Session,
    *,
    notify_email: str,
) -> OnboardingRegisterResult:
    user, _ = create_or_initialize_user(db, notify_email=notify_email)
    status = get_onboarding_status(db)
    if status.registered_user_id is None:
        raise OnboardingRegisterError("register user failed", status_code=422)

    return OnboardingRegisterResult(
        user_id=user.id,
        stage=status.stage,
        first_source_id=status.first_source_id,
    )
