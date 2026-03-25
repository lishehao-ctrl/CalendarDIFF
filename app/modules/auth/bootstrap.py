from __future__ import annotations

import logging

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.shared import User
from app.db.session import get_session_factory
from app.modules.auth.service import _hash_password, _normalize_email, _normalize_timezone_name

logger = logging.getLogger(__name__)


def ensure_env_admin_user(
    db: Session,
    *,
    email: str,
    password: str,
    timezone_name: str,
) -> User:
    normalized_email = _normalize_email(email)
    normalized_timezone = _normalize_timezone_name(timezone_name)

    user = db.scalar(select(User).where(User.email == normalized_email).limit(1))
    created = False
    if user is None:
        user = User(
            email=normalized_email,
            password_hash=_hash_password(password),
            timezone_name=normalized_timezone,
            timezone_source="manual",
            language_code="en",
            onboarding_completed_at=None,
        )
        db.add(user)
        created = True
    else:
        user.email = user.email or normalized_email
        user.password_hash = _hash_password(password)
        user.timezone_name = normalized_timezone
        user.timezone_source = "manual"
        user.language_code = user.language_code or "en"

    db.commit()
    db.refresh(user)
    logger.info(
        "bootstrap admin user %s email=%s user_id=%s",
        "created" if created else "updated",
        normalized_email,
        user.id,
    )
    return user


def bootstrap_env_admin_user(_: FastAPI) -> None:
    settings = get_settings()
    email = (settings.bootstrap_admin_email or "").strip()
    password = settings.bootstrap_admin_password or ""
    if not email or not password:
        return

    session_factory = get_session_factory()
    with session_factory() as db:
        ensure_env_admin_user(
            db,
            email=email,
            password=password,
            timezone_name=settings.bootstrap_admin_timezone_name,
        )


__all__ = ["bootstrap_env_admin_user", "ensure_env_admin_user"]
