from __future__ import annotations

import os

import bcrypt
from fastapi import FastAPI
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models.shared import User
from app.modules.auth.bootstrap import bootstrap_env_admin_user, ensure_env_admin_user


def test_ensure_env_admin_user_creates_user(db_session) -> None:
    user = ensure_env_admin_user(
        db_session,
        email="admin@example.com",
        password="123456",
        timezone_name="America/Los_Angeles",
    )

    assert user.email == "admin@example.com"
    assert user.email == "admin@example.com"
    assert user.timezone_name == "America/Los_Angeles"
    assert user.timezone_source == "manual"
    assert user.password_hash is not None
    assert bcrypt.checkpw(b"123456", user.password_hash.encode("utf-8"))


def test_ensure_env_admin_user_updates_existing_password(db_session) -> None:
    first = ensure_env_admin_user(
        db_session,
        email="admin@example.com",
        password="123456",
        timezone_name="UTC",
    )

    updated = ensure_env_admin_user(
        db_session,
        email="admin@example.com",
        password="abcdef",
        timezone_name="America/Los_Angeles",
    )

    assert updated.id == first.id
    assert updated.timezone_name == "America/Los_Angeles"
    assert bcrypt.checkpw(b"abcdef", updated.password_hash.encode("utf-8"))
    assert db_session.scalar(select(User).where(User.email == "admin@example.com").limit(1)).id == first.id


def test_bootstrap_env_admin_user_skips_when_env_missing(db_session, monkeypatch) -> None:
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_TIMEZONE_NAME", "America/Los_Angeles")
    get_settings.cache_clear()

    app = FastAPI()
    bootstrap_env_admin_user(app)

    assert db_session.scalar(select(User).limit(1)) is None


def test_bootstrap_env_admin_user_reads_env_and_creates_user(db_session, monkeypatch) -> None:
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "lishehao@gmail.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "123456")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_TIMEZONE_NAME", "America/Los_Angeles")
    get_settings.cache_clear()

    app = FastAPI()
    bootstrap_env_admin_user(app)

    db_session.expire_all()
    user = db_session.scalar(select(User).where(User.email == "lishehao@gmail.com").limit(1))
    get_settings.cache_clear()

    assert user is not None
    assert bcrypt.checkpw(b"123456", user.password_hash.encode("utf-8"))
