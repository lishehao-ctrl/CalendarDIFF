from __future__ import annotations

from datetime import date
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, UserTerm

EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")
USER_NOT_INITIALIZED_MESSAGE = "Create user first via POST /v1/user"


class UserNotInitializedError(RuntimeError):
    """Raised when endpoints require user initialization but no valid user exists."""


def user_not_initialized_detail() -> dict[str, str]:
    return {
        "code": "user_not_initialized",
        "message": USER_NOT_INITIALIZED_MESSAGE,
    }


def get_current_user(db: Session) -> User:
    return require_initialized_user(db)


def get_initialized_user(db: Session) -> User | None:
    user = db.scalar(select(User).order_by(User.id.asc()).limit(1))
    if user is None:
        return None
    if not _is_valid_email(user.notify_email):
        return None
    return user


def require_initialized_user(db: Session) -> User:
    user = get_initialized_user(db)
    if user is None:
        raise UserNotInitializedError(USER_NOT_INITIALIZED_MESSAGE)
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


def list_user_terms(db: Session, *, user_id: int) -> list[UserTerm]:
    return db.scalars(
        select(UserTerm)
        .where(UserTerm.user_id == user_id)
        .order_by(UserTerm.starts_on.asc(), UserTerm.id.asc())
    ).all()


def get_user_term_by_id(db: Session, *, user_id: int, term_id: int) -> UserTerm | None:
    return db.scalar(select(UserTerm).where(UserTerm.id == term_id, UserTerm.user_id == user_id))


def create_user_term(
    db: Session,
    *,
    user_id: int,
    code: str,
    label: str,
    starts_on: date,
    ends_on: date,
    is_active: bool = True,
) -> UserTerm:
    term = UserTerm(
        user_id=user_id,
        code=code.strip(),
        label=label.strip(),
        starts_on=starts_on,
        ends_on=ends_on,
        is_active=is_active,
    )
    db.add(term)
    db.commit()
    db.refresh(term)
    return term


def update_user_term(
    db: Session,
    *,
    term: UserTerm,
    code: str | None = None,
    label: str | None = None,
    starts_on: date | None = None,
    ends_on: date | None = None,
    is_active: bool | None = None,
) -> UserTerm:
    if code is not None:
        term.code = code.strip()
    if label is not None:
        term.label = label.strip()
    if starts_on is not None:
        term.starts_on = starts_on
    if ends_on is not None:
        term.ends_on = ends_on
    if term.ends_on < term.starts_on:
        raise ValueError("ends_on must be greater than or equal to starts_on")
    if is_active is not None:
        term.is_active = is_active

    db.commit()
    db.refresh(term)
    return term


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
