from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, UserTerm


def get_current_user(db: Session) -> User:
    return get_or_create_default_user(db)


def get_or_create_default_user(db: Session) -> User:
    user = db.scalar(select(User).order_by(User.id.asc()).limit(1))
    if user is not None:
        return user

    user = User(email=None)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


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
        user.notify_email = _normalize_optional_text(notify_email)
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
