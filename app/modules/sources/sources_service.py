from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import encrypt_secret
from app.db.models.input import InputSource, InputSourceConfig, InputSourceCursor, InputSourceSecret
from app.db.models.shared import User
from app.modules.common.source_term_window import parse_source_term_window, parse_term_window_config, source_timezone_name
from app.modules.sources.provider_sources import (
    CANVAS_ICS_DISPLAY_NAME,
    CANVAS_ICS_SOURCE_KEY,
    GmailSourceAlreadyExistsError,
    IcsSourceAlreadyExistsError,
    ensure_provider_source_available,
    get_canvas_ics_source_for_user,
    get_gmail_source_for_user,
    normalize_source_create_request,
    normalize_source_patch_request,
)
from app.modules.sources.schemas import InputSourceCreateRequest, InputSourcePatchRequest
from app.modules.sources.source_term_rebind import (
    has_active_sync_requests,
    queue_pending_term_rebind,
)
from app.modules.sources.source_term_rescope import apply_source_term_rescope, term_window_changed


def list_input_sources(db: Session, *, user_id: int, status: str = "active") -> list[InputSource]:
    stmt = select(InputSource).where(InputSource.user_id == user_id)
    normalized_status = status.strip().lower() if isinstance(status, str) else "active"
    if normalized_status == "active":
        stmt = stmt.where(InputSource.is_active.is_(True))
    elif normalized_status == "archived":
        stmt = stmt.where(InputSource.is_active.is_(False))
    stmt = stmt.order_by(InputSource.updated_at.desc(), InputSource.id.desc())
    return list(db.scalars(stmt).all())


def get_input_source(db: Session, *, user_id: int, source_id: int) -> InputSource | None:
    return db.scalar(
        select(InputSource)
        .where(
            InputSource.id == source_id,
            InputSource.user_id == user_id,
        )
    )


def get_canvas_ics_source(db: Session, *, user_id: int) -> InputSource | None:
    return get_canvas_ics_source_for_user(db, user_id=user_id)


def get_gmail_source(db: Session, *, user_id: int) -> InputSource | None:
    return get_gmail_source_for_user(db, user_id=user_id)


def create_input_source(db: Session, *, user: User, payload: InputSourceCreateRequest) -> InputSource:
    normalized = normalize_source_create_request(payload)
    if normalized.provider in {"gmail", "ics"}:
        ensure_provider_source_available(db, user_id=user.id, provider=normalized.provider)

    now = datetime.now(timezone.utc)
    initial_next_poll_at = now
    term_window = parse_term_window_config(normalized.config, required=False)
    if term_window is not None:
        initial_next_poll_at = max(now, term_window.monitor_start_at_utc(timezone_name=user.timezone_name))
    source = InputSource(
        user_id=user.id,
        source_kind=normalized.source_kind,
        provider=normalized.provider,
        source_key=normalized.source_key,
        display_name=normalized.display_name,
        is_active=True,
        poll_interval_seconds=normalized.poll_interval_seconds,
        last_polled_at=None,
        next_poll_at=initial_next_poll_at,
    )
    db.add(source)
    db.flush()

    db.add(
        InputSourceConfig(
            source_id=source.id,
            schema_version=1,
            config_json=normalized.config,
        )
    )
    db.add(
        InputSourceSecret(
            source_id=source.id,
            encrypted_payload=encrypt_secret(json.dumps(normalized.secrets, separators=(",", ":"), ensure_ascii=True)),
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


def upsert_canvas_ics_source(
    db: Session,
    *,
    user: User,
    url: str,
    term_key: str,
    term_from: str,
    term_to: str,
    poll_interval_seconds: int = 900,
) -> InputSource:
    existing = get_canvas_ics_source_for_user(db, user_id=user.id)
    if existing is not None:
        payload = InputSourcePatchRequest(
            is_active=True,
            poll_interval_seconds=poll_interval_seconds,
            config={"term_key": term_key, "term_from": term_from, "term_to": term_to},
            secrets={"url": url},
        )
        return update_input_source(db, source=existing, payload=payload)

    return create_input_source(
        db,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="calendar",
            provider="ics",
            poll_interval_seconds=poll_interval_seconds,
            config={"term_key": term_key, "term_from": term_from, "term_to": term_to},
            secrets={"url": url},
        ),
    )


def update_input_source(
    db: Session,
    *,
    source: InputSource,
    payload: InputSourcePatchRequest,
) -> InputSource:
    now = datetime.now(timezone.utc)
    normalized = normalize_source_patch_request(source=source, payload=payload)
    previous_term_window = parse_source_term_window(source, required=False)
    next_term_window = previous_term_window
    should_rescope_term_window = False
    config_term_rebind_queued = False

    if payload.display_name is not None and normalized.allow_display_name_update:
        source.display_name = normalized.display_name
    if normalized.is_active is not None:
        source.is_active = normalized.is_active
    if normalized.poll_interval_seconds is not None:
        source.poll_interval_seconds = normalized.poll_interval_seconds
        if source.next_poll_at is None:
            source.next_poll_at = now + timedelta(seconds=normalized.poll_interval_seconds)
    if normalized.config is not None:
        requested_config = dict(normalized.config)
        requested_term_window = parse_term_window_config(requested_config, required=False)
        requested_term_changed = term_window_changed(previous=previous_term_window, current=requested_term_window)
        if requested_term_changed and has_active_sync_requests(db=db, source_id=source.id):
            queue_pending_term_rebind(
                source=source,
                requested_config=requested_config,
                requested_at=now,
                requested_by_user_id=source.user_id,
            )
            next_term_window = previous_term_window
            should_rescope_term_window = False
            config_term_rebind_queued = True
        else:
            if source.config is None:
                source.config = InputSourceConfig(source_id=source.id, schema_version=1, config_json=requested_config)
            else:
                source.config.config_json = requested_config
            next_term_window = parse_source_term_window(source, required=False)
            should_rescope_term_window = term_window_changed(previous=previous_term_window, current=next_term_window)
            if source.is_active:
                if next_term_window is not None and next_term_window.is_expired(
                    now=now,
                    timezone_name=source_timezone_name(source),
                ):
                    source.is_active = False
                    source.next_poll_at = None
                elif next_term_window is not None:
                    source.next_poll_at = max(
                        now,
                        next_term_window.monitor_start_at_utc(timezone_name=source_timezone_name(source)),
                    )
                else:
                    source.next_poll_at = source.next_poll_at or now
    if normalized.secrets is not None:
        encrypted_payload = encrypt_secret(json.dumps(normalized.secrets, separators=(",", ":"), ensure_ascii=True))
        if source.secrets is None:
            source.secrets = InputSourceSecret(source_id=source.id, encrypted_payload=encrypted_payload)
        else:
            source.secrets.encrypted_payload = encrypted_payload
        if normalized.reactivate_on_secret_update and payload.is_active is None and not source.is_active:
            source.is_active = True
        if normalized.reactivate_on_secret_update and source.next_poll_at is None:
            term_window = next_term_window if next_term_window is not None else parse_source_term_window(source, required=False)
            if term_window is not None:
                source.next_poll_at = max(now, term_window.monitor_start_at_utc(timezone_name=source_timezone_name(source)))
            else:
                source.next_poll_at = now + timedelta(seconds=source.poll_interval_seconds)
    if normalized.force_source_key is not None:
        source.source_key = normalized.force_source_key
    if normalized.force_display_name is not None:
        source.display_name = normalized.force_display_name
    if normalized.is_active is True and source.next_poll_at is None:
        term_window = next_term_window if next_term_window is not None else parse_source_term_window(source, required=False)
        if term_window is not None:
            if term_window.is_expired(now=now, timezone_name=source_timezone_name(source)):
                source.is_active = False
                source.next_poll_at = None
            else:
                source.next_poll_at = max(now, term_window.monitor_start_at_utc(timezone_name=source_timezone_name(source)))
        else:
            source.next_poll_at = now + timedelta(seconds=source.poll_interval_seconds)
    if normalized.is_active is False:
        source.next_poll_at = None
    if should_rescope_term_window and next_term_window is not None and not config_term_rebind_queued:
        apply_source_term_rescope(
            db=db,
            source=source,
            term_window=next_term_window,
            applied_at=now,
        )
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


__all__ = [
    "CANVAS_ICS_DISPLAY_NAME",
    "CANVAS_ICS_SOURCE_KEY",
    "GmailSourceAlreadyExistsError",
    "IcsSourceAlreadyExistsError",
    "create_input_source",
    "get_canvas_ics_source",
    "get_gmail_source",
    "get_input_source",
    "list_input_sources",
    "soft_delete_input_source",
    "update_input_source",
    "upsert_canvas_ics_source",
]
