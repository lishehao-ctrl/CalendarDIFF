from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource, SourceKind
from app.modules.common.source_term_window import normalize_term_window_config
from app.modules.input_control_plane.schemas import InputSourceCreateRequest, InputSourcePatchRequest

CANVAS_ICS_SOURCE_KEY = "canvas_ics"
CANVAS_ICS_DISPLAY_NAME = "Canvas ICS"


class ProviderSourceAlreadyExistsError(RuntimeError):
    def __init__(self, *, provider: str, source_id: int) -> None:
        self.provider = provider
        self.source_id = source_id
        super().__init__(f"{provider} source already exists for this user (source_id={source_id})")


class GmailSourceAlreadyExistsError(ProviderSourceAlreadyExistsError):
    def __init__(self, *, source_id: int) -> None:
        super().__init__(provider="gmail", source_id=source_id)


class IcsSourceAlreadyExistsError(ProviderSourceAlreadyExistsError):
    def __init__(self, *, source_id: int) -> None:
        super().__init__(provider="ics", source_id=source_id)


@dataclass(frozen=True)
class NormalizedSourceCreate:
    source_kind: SourceKind
    provider: str
    source_key: str
    display_name: str | None
    poll_interval_seconds: int
    config: dict[str, Any]
    secrets: dict[str, Any]


@dataclass(frozen=True)
class NormalizedSourcePatch:
    display_name: str | None = None
    allow_display_name_update: bool = True
    is_active: bool | None = None
    poll_interval_seconds: int | None = None
    config: dict[str, Any] | None = None
    secrets: dict[str, Any] | None = None
    force_source_key: str | None = None
    force_display_name: str | None = None
    reactivate_on_secret_update: bool = False


def get_provider_source_for_user(db: Session, *, user_id: int, provider: str) -> InputSource | None:
    return db.scalar(
        select(InputSource)
        .where(
            InputSource.user_id == user_id,
            InputSource.provider == provider,
        )
        .order_by(InputSource.created_at.desc(), InputSource.id.desc())
        .limit(1)
    )


def get_canvas_ics_source_for_user(db: Session, *, user_id: int) -> InputSource | None:
    return get_provider_source_for_user(db, user_id=user_id, provider="ics")


def get_gmail_source_for_user(db: Session, *, user_id: int) -> InputSource | None:
    return get_provider_source_for_user(db, user_id=user_id, provider="gmail")


def ensure_provider_source_available(db: Session, *, user_id: int, provider: str) -> None:
    existing = get_provider_source_for_user(db, user_id=user_id, provider=provider)
    if existing is None:
        return
    if provider == "gmail":
        raise GmailSourceAlreadyExistsError(source_id=existing.id)
    if provider == "ics":
        raise IcsSourceAlreadyExistsError(source_id=existing.id)
    raise ProviderSourceAlreadyExistsError(provider=provider, source_id=existing.id)


def normalize_source_create_request(payload: InputSourceCreateRequest) -> NormalizedSourceCreate:
    normalized_provider = payload.provider.strip().lower()
    source_kind = SourceKind(payload.source_kind)
    source_key = (payload.source_key or "").strip() or build_source_key(
        source_kind=payload.source_kind,
        provider=normalized_provider,
        config=payload.config,
    )
    display_name = normalize_optional_text(payload.display_name)
    config = dict(payload.config)
    secrets = dict(payload.secrets)

    if normalized_provider == "ics":
        source_kind = SourceKind.CALENDAR
        source_key = CANVAS_ICS_SOURCE_KEY
        display_name = CANVAS_ICS_DISPLAY_NAME
        config = normalize_term_window_config(config=config, required=True)
        secrets = normalize_ics_secrets(payload.secrets)
    elif normalized_provider == "gmail":
        config = normalize_term_window_config(config=config, required=True)

    return NormalizedSourceCreate(
        source_kind=source_kind,
        provider=normalized_provider,
        source_key=source_key,
        display_name=display_name,
        poll_interval_seconds=payload.poll_interval_seconds,
        config=config,
        secrets=secrets,
    )


def normalize_source_patch_request(*, source: InputSource, payload: InputSourcePatchRequest) -> NormalizedSourcePatch:
    if source.provider == "ics":
        return NormalizedSourcePatch(
            allow_display_name_update=False,
            is_active=payload.is_active,
            poll_interval_seconds=payload.poll_interval_seconds,
            config=normalize_term_window_config(config=dict(payload.config), required=True) if payload.config is not None else None,
            secrets=normalize_ics_secrets(payload.secrets) if payload.secrets is not None else None,
            force_source_key=CANVAS_ICS_SOURCE_KEY,
            force_display_name=CANVAS_ICS_DISPLAY_NAME,
            reactivate_on_secret_update=True,
        )
    if source.provider == "gmail":
        return NormalizedSourcePatch(
            display_name=normalize_optional_text(payload.display_name),
            allow_display_name_update=True,
            is_active=payload.is_active,
            poll_interval_seconds=payload.poll_interval_seconds,
            config=normalize_term_window_config(config=dict(payload.config), required=True) if payload.config is not None else None,
            secrets=dict(payload.secrets) if payload.secrets is not None else None,
        )

    return NormalizedSourcePatch(
        display_name=normalize_optional_text(payload.display_name),
        allow_display_name_update=True,
        is_active=payload.is_active,
        poll_interval_seconds=payload.poll_interval_seconds,
        config=dict(payload.config) if payload.config is not None else None,
        secrets=dict(payload.secrets) if payload.secrets is not None else None,
    )


def build_source_key(*, source_kind: str, provider: str, config: dict[str, Any]) -> str:
    payload = {
        "source_kind": source_kind,
        "provider": provider,
        "config": config,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return digest


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def normalize_ics_secrets(secrets: dict[str, Any]) -> dict[str, str]:
    url = secrets.get("url") if isinstance(secrets, dict) else None
    if not isinstance(url, str) or not url.strip():
        raise ValueError("ics source requires a non-empty secrets.url")
    return {"url": url.strip()}


__all__ = [
    "CANVAS_ICS_DISPLAY_NAME",
    "CANVAS_ICS_SOURCE_KEY",
    "GmailSourceAlreadyExistsError",
    "IcsSourceAlreadyExistsError",
    "NormalizedSourceCreate",
    "NormalizedSourcePatch",
    "build_source_key",
    "ensure_provider_source_available",
    "get_canvas_ics_source_for_user",
    "get_gmail_source_for_user",
    "get_provider_source_for_user",
    "normalize_optional_text",
    "normalize_source_create_request",
    "normalize_source_patch_request",
]
