from __future__ import annotations

from datetime import date
import re

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db.models import User, UserTerm

EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")
USER_NOT_INITIALIZED_MESSAGE = "Create user first via POST /v1/user"
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


# Backward-compatible aliases while call sites migrate.
def get_initialized_user(db: Session) -> User | None:
    return get_registered_user(db)


def require_initialized_user(db: Session) -> User:
    return require_registered_user(db)


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
    normalized_code = code.strip()
    normalized_label = label.strip()
    if not normalized_code:
        raise ValueError("code must not be blank")
    if not normalized_label:
        raise ValueError("label must not be blank")
    if ends_on < starts_on:
        raise ValueError("ends_on must be greater than or equal to starts_on")
    if is_active:
        _assert_no_active_term_overlap(db, user_id=user_id, starts_on=starts_on, ends_on=ends_on, exclude_term_id=None)

    term = UserTerm(
        user_id=user_id,
        code=normalized_code,
        label=normalized_label,
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
    next_code = code.strip() if code is not None else term.code
    next_label = label.strip() if label is not None else term.label
    next_starts_on = starts_on if starts_on is not None else term.starts_on
    next_ends_on = ends_on if ends_on is not None else term.ends_on
    next_is_active = is_active if is_active is not None else term.is_active

    if not next_code:
        raise ValueError("code must not be blank")
    if not next_label:
        raise ValueError("label must not be blank")
    if next_ends_on < next_starts_on:
        raise ValueError("ends_on must be greater than or equal to starts_on")
    if next_is_active:
        _assert_no_active_term_overlap(
            db,
            user_id=term.user_id,
            starts_on=next_starts_on,
            ends_on=next_ends_on,
            exclude_term_id=term.id,
        )

    term.code = next_code
    term.label = next_label
    term.starts_on = next_starts_on
    term.ends_on = next_ends_on
    term.is_active = next_is_active

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


def _assert_no_active_term_overlap(
    db: Session,
    *,
    user_id: int,
    starts_on: date,
    ends_on: date,
    exclude_term_id: int | None,
) -> None:
    stmt = select(UserTerm).where(
        and_(
            UserTerm.user_id == user_id,
            UserTerm.is_active.is_(True),
            UserTerm.starts_on <= ends_on,
            UserTerm.ends_on >= starts_on,
        )
    )
    if exclude_term_id is not None:
        stmt = stmt.where(UserTerm.id != exclude_term_id)
    overlap = db.scalar(stmt.order_by(UserTerm.starts_on.asc(), UserTerm.id.asc()).limit(1))
    if overlap is not None:
        raise ValueError("active term window overlaps existing active term")
