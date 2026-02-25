from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User

EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")
USER_NOT_INITIALIZED_MESSAGE = "Initialize user via POST /v1/onboarding/register"
USER_ONBOARDING_INCOMPLETE_MESSAGE = "Complete onboarding via POST /v1/onboarding/register"


class UserNotInitializedError(RuntimeError):
    """Raised when endpoints require user initialization but no valid user exists."""


class UserOnboardingIncompleteError(RuntimeError):
    """Raised when endpoints require completed onboarding but user is not ready."""


def user_not_initialized_detail() -> dict[str, str]:
    return {
        "code": "user_not_initialized",
        "message": USER_NOT_INITIALIZED_MESSAGE,
    }


def user_onboarding_incomplete_detail() -> dict[str, str]:
    return {
        "code": "user_onboarding_incomplete",
        "message": USER_ONBOARDING_INCOMPLETE_MESSAGE,
    }


def get_current_user(db: Session) -> User:
    return require_registered_user(db)


def get_registered_user(db: Session) -> User | None:
    user = db.scalar(select(User).order_by(User.id.asc()).limit(1))
    if user is None:
        return None
    if not _is_valid_email(user.notify_email):
        return None
    return user


def require_registered_user(db: Session) -> User:
    user = get_registered_user(db)
    if user is None:
        raise UserNotInitializedError(USER_NOT_INITIALIZED_MESSAGE)
    return user


def get_onboarded_user(db: Session) -> User | None:
    user = get_registered_user(db)
    if user is None:
        return None
    if user.onboarding_completed_at is None:
        return None
    return user


def require_onboarded_user(db: Session) -> User:
    user = get_registered_user(db)
    if user is None:
        raise UserNotInitializedError(USER_NOT_INITIALIZED_MESSAGE)
    if user.onboarding_completed_at is None:
        raise UserOnboardingIncompleteError(USER_ONBOARDING_INCOMPLETE_MESSAGE)
    return user


def create_or_initialize_user(db: Session, *, notify_email: str) -> tuple[User, bool]:
    normalized_notify_email = _normalize_required_email(notify_email)
    user = db.scalar(select(User).order_by(User.id.asc()).limit(1))

    if user is not None:
        if _is_valid_email(user.notify_email):
            return user, False
        user.notify_email = normalized_notify_email
        db.commit()
        db.refresh(user)
        return user, True

    user = User(email=None, notify_email=normalized_notify_email)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, True


def update_current_user(
    db: Session,
    *,
    user: User,
    email: str | None = None,
    notify_email: str | None = None,
    calendar_delay_seconds: int | None = None,
) -> User:
    if email is not None:
        user.email = _normalize_optional_text(email)
    if notify_email is not None:
        user.notify_email = _normalize_required_email(notify_email)
    if calendar_delay_seconds is not None:
        user.calendar_delay_seconds = calendar_delay_seconds
    db.commit()
    db.refresh(user)
    return user


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_required_email(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("notify_email must not be blank")
    if not EMAIL_PATTERN.fullmatch(stripped):
        raise ValueError("notify_email must be a valid email address")
    return stripped


def _is_valid_email(value: str | None) -> bool:
    if value is None:
        return False
    return EMAIL_PATTERN.fullmatch(value.strip()) is not None
