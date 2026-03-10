from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.shared import User, UserSession
from app.modules.users.email_utils import is_valid_email_address

AUTH_SESSION_COOKIE_NAME = "calendardiff_session"
AUTH_SESSION_TTL = timedelta(days=7)


class AuthEmailExistsError(RuntimeError):
    pass


class InvalidCredentialsError(RuntimeError):
    pass


class AuthenticationRequiredError(RuntimeError):
    pass


def register_user(db: Session, *, notify_email: str, password: str) -> User:
    normalized_email = _normalize_notify_email(notify_email)
    _validate_password(password)

    existing = db.scalar(select(User).where(User.notify_email == normalized_email).limit(1))
    if existing is not None:
        raise AuthEmailExistsError("notify_email already exists")

    user = User(
        email=None,
        notify_email=normalized_email,
        password_hash=_hash_password(password),
        timezone_name="UTC",
        onboarding_completed_at=None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def login_user(db: Session, *, notify_email: str, password: str) -> User:
    normalized_email = _normalize_notify_email(notify_email)
    user = db.scalar(select(User).where(User.notify_email == normalized_email).limit(1))
    if user is None or not user.password_hash:
        raise InvalidCredentialsError("invalid credentials")
    if not bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8")):
        raise InvalidCredentialsError("invalid credentials")
    return user


def create_user_session(db: Session, *, user: User, now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    session_id = secrets.token_urlsafe(32)
    row = UserSession(
        session_id=session_id,
        user_id=user.id,
        expires_at=current + AUTH_SESSION_TTL,
        last_seen_at=current,
    )
    db.add(row)
    db.commit()
    return _encode_cookie_value(session_id)


def delete_user_session(db: Session, *, cookie_value: str | None) -> None:
    session_id = _decode_cookie_value(cookie_value)
    if not session_id:
        return
    db.execute(delete(UserSession).where(UserSession.session_id == session_id))
    db.commit()


def get_authenticated_user_from_request(db: Session, *, request: Request, now: datetime | None = None) -> User:
    current = now or datetime.now(timezone.utc)
    session_cookie = request.cookies.get(AUTH_SESSION_COOKIE_NAME)
    session_id = _decode_cookie_value(session_cookie)
    if not session_id:
        raise AuthenticationRequiredError("authentication required")

    row = db.scalar(
        select(UserSession)
        .where(UserSession.session_id == session_id)
        .limit(1)
    )
    if row is None or row.expires_at <= current:
        if row is not None:
            db.delete(row)
            db.commit()
        raise AuthenticationRequiredError("authentication required")

    row.last_seen_at = current
    db.commit()
    db.refresh(row)
    return row.user


def build_session_cookie_kwargs() -> dict[str, object]:
    secure = bool(get_settings().frontend_app_base_url and get_settings().frontend_app_base_url.startswith("https://"))
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
        "path": "/",
        "max_age": int(AUTH_SESSION_TTL.total_seconds()),
    }


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")


def _normalize_notify_email(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("notify_email must not be blank")
    if not is_valid_email_address(normalized):
        raise ValueError("notify_email must be a valid email address")
    return normalized


def _encode_cookie_value(session_id: str) -> str:
    digest = hmac.new(get_settings().app_secret_key.encode("utf-8"), session_id.encode("utf-8"), hashlib.sha256).digest()
    signature = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return f"{session_id}.{signature}"


def _decode_cookie_value(cookie_value: str | None) -> str | None:
    if not cookie_value or "." not in cookie_value:
        return None
    session_id, signature = cookie_value.rsplit(".", 1)
    expected = _encode_cookie_value(session_id).rsplit(".", 1)[1]
    if not hmac.compare_digest(signature, expected):
        return None
    return session_id
