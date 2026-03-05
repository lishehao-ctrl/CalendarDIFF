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
    source_key = (payload.source_key or "").strip() or _build_source_key(
        source_kind=payload.source_kind,
        provider=normalized_provider,
        config=payload.config,
    )
    now = datetime.now(timezone.utc)

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind(payload.source_kind),
        provider=normalized_provider,
        source_key=source_key,
        display_name=_normalize_optional_text(payload.display_name),
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
            config_json=dict(payload.config),
        )
    )
    db.add(
        InputSourceSecret(
            source_id=source.id,
            encrypted_payload=encrypt_secret(json.dumps(payload.secrets, separators=(",", ":"), ensure_ascii=True)),
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
    if payload.display_name is not None:
        source.display_name = _normalize_optional_text(payload.display_name)
    if payload.is_active is not None:
        source.is_active = payload.is_active
    if payload.poll_interval_seconds is not None:
        source.poll_interval_seconds = payload.poll_interval_seconds
        if source.next_poll_at is None:
            source.next_poll_at = now + timedelta(seconds=payload.poll_interval_seconds)
    if payload.config is not None:
        if source.config is None:
            source.config = InputSourceConfig(source_id=source.id, schema_version=1, config_json=dict(payload.config))
        else:
            source.config.config_json = dict(payload.config)
    if payload.secrets is not None:
        encrypted_payload = encrypt_secret(json.dumps(payload.secrets, separators=(",", ":"), ensure_ascii=True))
        if source.secrets is None:
            source.secrets = InputSourceSecret(source_id=source.id, encrypted_payload=encrypted_payload)
        else:
            source.secrets.encrypted_payload = encrypted_payload
    db.commit()
    db.refresh(source)
    return source


def soft_delete_input_source(db: Session, *, source: InputSource) -> None:
    source.is_active = False
    source.next_poll_at = None
    db.commit()


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _build_source_key(*, source_kind: str, provider: str, config: dict) -> str:
    payload = {
        "source_kind": source_kind,
        "provider": provider,
        "config": config,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return digest


__all__ = [
    "create_input_source",
    "get_input_source",
    "list_input_sources",
    "soft_delete_input_source",
    "update_input_source",
]
