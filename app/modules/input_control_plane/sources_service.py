from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import encrypt_secret
from app.db.models.input import InputSource, InputSourceConfig, InputSourceCursor, InputSourceSecret, SourceKind
from app.db.models.shared import User
from app.modules.input_control_plane.schemas import InputSourceCreateRequest, InputSourcePatchRequest

CANVAS_ICS_SOURCE_KEY = "canvas_ics"
CANVAS_ICS_DISPLAY_NAME = "Canvas ICS"


class GmailSourceAlreadyExistsError(RuntimeError):
    def __init__(self, *, source_id: int) -> None:
        self.source_id = source_id
        super().__init__(f"gmail source already exists for this user (source_id={source_id})")


class IcsSourceAlreadyExistsError(RuntimeError):
    def __init__(self, *, source_id: int) -> None:
        self.source_id = source_id
        super().__init__(f"ics source already exists for this user (source_id={source_id})")


def list_input_sources(db: Session, *, user_id: int) -> list[InputSource]:
    return list(
        db.scalars(
            select(InputSource)
            .where(InputSource.user_id == user_id)
            .order_by(InputSource.created_at.desc(), InputSource.id.desc())
        ).all()
    )


def get_input_source(db: Session, *, user_id: int, source_id: int) -> InputSource | None:
    return db.scalar(
        select(InputSource)
        .where(
            InputSource.id == source_id,
            InputSource.user_id == user_id,
        )
    )


def create_input_source(db: Session, *, user: User, payload: InputSourceCreateRequest) -> InputSource:
    normalized_provider = payload.provider.strip().lower()
    if normalized_provider == "gmail":
        existing = _get_existing_source_for_provider(db=db, user_id=user.id, provider="gmail")
        if existing is not None:
            raise GmailSourceAlreadyExistsError(source_id=existing.id)
    if normalized_provider == "ics":
        existing = _get_existing_source_for_provider(db=db, user_id=user.id, provider="ics")
        if existing is not None:
            raise IcsSourceAlreadyExistsError(source_id=existing.id)

    source_kind = SourceKind(payload.source_kind)
    source_key = (payload.source_key or "").strip() or _build_source_key(
        source_kind=payload.source_kind,
        provider=normalized_provider,
        config=payload.config,
    )
    display_name = _normalize_optional_text(payload.display_name)
    config = dict(payload.config)
    secrets = dict(payload.secrets)

    if normalized_provider == "ics":
        source_kind = SourceKind.CALENDAR
        source_key = CANVAS_ICS_SOURCE_KEY
        display_name = CANVAS_ICS_DISPLAY_NAME
        config = {}
        secrets = _normalize_ics_secrets(payload.secrets)

    now = datetime.now(timezone.utc)
    source = InputSource(
        user_id=user.id,
        source_kind=source_kind,
        provider=normalized_provider,
        source_key=source_key,
        display_name=display_name,
        is_active=True,
        poll_interval_seconds=payload.poll_interval_seconds,
        last_polled_at=None,
        next_poll_at=now,
    )
    db.add(source)
    db.flush()

    db.add(
        InputSourceConfig(
            source_id=source.id,
            schema_version=1,
            config_json=config,
        )
    )
    db.add(
        InputSourceSecret(
            source_id=source.id,
            encrypted_payload=encrypt_secret(json.dumps(secrets, separators=(",", ":"), ensure_ascii=True)),
        )
    )
    db.add(
        InputSourceCursor(
            source_id=source.id,
            version=1,
            cursor_json={},
        )
    )
    if user.onboarding_completed_at is None:
        user.onboarding_completed_at = now

    db.commit()
    db.refresh(source)
    return source


def update_input_source(
    db: Session,
    *,
    source: InputSource,
    payload: InputSourcePatchRequest,
) -> InputSource:
    now = datetime.now(timezone.utc)
    is_ics = source.provider == "ics"

    if payload.display_name is not None and not is_ics:
        source.display_name = _normalize_optional_text(payload.display_name)
    if payload.is_active is not None:
        source.is_active = payload.is_active
    if payload.poll_interval_seconds is not None:
        source.poll_interval_seconds = payload.poll_interval_seconds
        if source.next_poll_at is None:
            source.next_poll_at = now + timedelta(seconds=payload.poll_interval_seconds)
    if payload.config is not None:
        config_json = {} if is_ics else dict(payload.config)
        if source.config is None:
            source.config = InputSourceConfig(source_id=source.id, schema_version=1, config_json=config_json)
        else:
            source.config.config_json = config_json
    if payload.secrets is not None:
        secret_payload = _normalize_ics_secrets(payload.secrets) if is_ics else dict(payload.secrets)
        encrypted_payload = encrypt_secret(json.dumps(secret_payload, separators=(",", ":"), ensure_ascii=True))
        if source.secrets is None:
            source.secrets = InputSourceSecret(source_id=source.id, encrypted_payload=encrypted_payload)
        else:
            source.secrets.encrypted_payload = encrypted_payload
        if is_ics and payload.is_active is None and not source.is_active:
            source.is_active = True
        if is_ics and source.next_poll_at is None:
            source.next_poll_at = now + timedelta(seconds=source.poll_interval_seconds)
        source.source_key = CANVAS_ICS_SOURCE_KEY
        source.display_name = CANVAS_ICS_DISPLAY_NAME
    db.commit()
    db.refresh(source)
    return source


def soft_delete_input_source(db: Session, *, source: InputSource) -> None:
    source.is_active = False
    source.next_poll_at = None
    if source.provider == "gmail":
        source.last_error_code = None
        source.last_error_message = None
        source.secrets = None
        source.cursor = None
    db.commit()


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_ics_secrets(secrets: dict) -> dict[str, str]:
    url = secrets.get("url") if isinstance(secrets, dict) else None
    if not isinstance(url, str) or not url.strip():
        raise ValueError("ics source requires a non-empty secrets.url")
    return {"url": url.strip()}


def _build_source_key(*, source_kind: str, provider: str, config: dict) -> str:
    payload = {
        "source_kind": source_kind,
        "provider": provider,
        "config": config,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return digest


def _get_existing_source_for_provider(*, db: Session, user_id: int, provider: str) -> InputSource | None:
    return db.scalar(
        select(InputSource)
        .where(
            InputSource.user_id == user_id,
            InputSource.provider == provider,
        )
        .order_by(InputSource.created_at.desc(), InputSource.id.desc())
        .limit(1)
    )


__all__ = [
    "CANVAS_ICS_DISPLAY_NAME",
    "CANVAS_ICS_SOURCE_KEY",
    "GmailSourceAlreadyExistsError",
    "IcsSourceAlreadyExistsError",
    "create_input_source",
    "get_input_source",
    "list_input_sources",
    "soft_delete_input_source",
    "update_input_source",
]
