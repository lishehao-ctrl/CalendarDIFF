from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Input, InputSource, InputType, User
from app.modules.users.email_utils import is_valid_email_address

USER_NOT_INITIALIZED_MESSAGE = "Initialize user via POST /v2/onboarding/registrations"
USER_ONBOARDING_INCOMPLETE_MESSAGE = "Connect at least one active input source via /v2/input-sources"


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
    if not has_active_input_source(db, user_id=user.id):
        return None
    return user


def require_onboarded_user(db: Session) -> User:
    user = get_registered_user(db)
    if user is None:
        raise UserNotInitializedError(USER_NOT_INITIALIZED_MESSAGE)
    if not has_active_input_source(db, user_id=user.id):
        raise UserOnboardingIncompleteError(USER_ONBOARDING_INCOMPLETE_MESSAGE)
    return user


def has_active_input_source(db: Session, *, user_id: int) -> bool:
    return (
        db.scalar(
            select(InputSource.id)
            .where(
                InputSource.user_id == user_id,
                InputSource.is_active.is_(True),
            )
            .limit(1)
        )
        is not None
    )


def get_first_active_input_source(db: Session, *, user_id: int) -> InputSource | None:
    return db.scalar(
        select(InputSource)
        .where(
            InputSource.user_id == user_id,
            InputSource.is_active.is_(True),
        )
        .order_by(InputSource.id.asc())
        .limit(1)
    )


def get_single_ics_input_for_user(
    db: Session,
    *,
    user_id: int,
    require_active: bool = False,
    for_update: bool = False,
) -> Input | None:
    stmt = select(Input).where(Input.user_id == user_id, Input.type == InputType.ICS)
    if require_active:
        stmt = stmt.where(Input.is_active.is_(True))
    stmt = stmt.order_by(Input.id.asc()).limit(2)
    if for_update:
        stmt = stmt.with_for_update()

    rows = db.scalars(stmt).all()
    if len(rows) != 1:
        return None
    return rows[0]


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
    if not is_valid_email_address(stripped):
        raise ValueError("notify_email must be a valid email address")
    return stripped


def _is_valid_email(value: str | None) -> bool:
    return is_valid_email_address(value)
