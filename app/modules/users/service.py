from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from app.db.models.input import InputSource
from app.db.models.review import Input, InputType
from app.db.models.shared import User
from app.modules.users.email_utils import is_valid_email_address

USER_NOT_INITIALIZED_MESSAGE = "Initialize user via /auth/register"
USER_ONBOARDING_INCOMPLETE_MESSAGE = "Connect at least one active input source via /sources"


class UserNotInitializedError(RuntimeError):
    pass


class UserOnboardingIncompleteError(RuntimeError):
    pass


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


def update_current_user(
    db: Session,
    *,
    user: User,
    email: str | None = None,
    notify_email: str | None = None,
    timezone_name: str | None = None,
    calendar_delay_seconds: int | None = None,
) -> User:
    if email is not None:
        user.email = _normalize_optional_text(email)
    if notify_email is not None and notify_email != user.notify_email:
        raise ValueError("notify_email is managed by auth and cannot be changed here")
    if timezone_name is not None:
        user.timezone_name = _normalize_timezone_name(timezone_name)
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


def _normalize_timezone_name(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("timezone_name must not be blank")
    try:
        ZoneInfo(stripped)
    except Exception as exc:
        raise ValueError("timezone_name must be a valid IANA timezone") from exc
    return stripped
