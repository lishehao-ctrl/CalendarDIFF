from __future__ import annotations

from email.utils import parseaddr
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.models.shared import User

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

def update_current_user(
    db: Session,
    *,
    user: User,
    email: str | None = None,
    notify_email: str | None = None,
    timezone_name: str | None = None,
    timezone_source: str | None = None,
    calendar_delay_seconds: int | None = None,
) -> User:
    if email is not None:
        user.email = _normalize_optional_text(email)
    if notify_email is not None and notify_email != user.notify_email:
        raise ValueError("notify_email is managed by auth and cannot be changed here")
    if timezone_name is not None:
        user.timezone_name = _normalize_timezone_name(timezone_name)
        user.timezone_source = _normalize_timezone_source(timezone_source) if timezone_source is not None else "manual"
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
    if not _is_valid_email_address(stripped):
        raise ValueError("notify_email must be a valid email address")
    return stripped


def _is_valid_email(value: str | None) -> bool:
    return _is_valid_email_address(value)


def sync_auto_timezone(
    db: Session,
    *,
    user: User,
    timezone_name: str | None,
) -> User:
    if timezone_name is None or user.timezone_source != "auto":
        return user
    normalized = _normalize_timezone_name(timezone_name)
    if user.timezone_name == normalized:
        return user
    user.timezone_name = normalized
    user.timezone_source = "auto"
    db.commit()
    db.refresh(user)
    return user


def _normalize_timezone_source(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"auto", "manual"}:
        raise ValueError("timezone_source must be either 'auto' or 'manual'")
    return normalized


def _is_valid_email_address(value: str | None) -> bool:
    if value is None:
        return False
    candidate = value.strip()
    if not candidate:
        return False
    if any(ch.isspace() for ch in candidate):
        return False
    _, parsed = parseaddr(candidate)
    if parsed != candidate:
        return False
    local, separator, domain = candidate.rpartition("@")
    if separator != "@":
        return False
    if not local or not domain or "." not in domain:
        return False
    if domain.startswith(".") or domain.endswith(".") or ".." in domain:
        return False
    return True


def _normalize_timezone_name(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("timezone_name must not be blank")
    try:
        ZoneInfo(stripped)
    except Exception as exc:
        raise ValueError("timezone_name must be a valid IANA timezone") from exc
    return stripped
