from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import encrypt_secret
from app.db.models.input import InputSource, InputSourceConfig, InputSourceCursor, InputSourceSecret, SourceKind
from app.db.models.shared import User
from app.modules.common.source_monitoring_window import (
    SourceMonitoringWindow,
    normalize_monitoring_window_config,
    parse_monitoring_window_config,
    parse_source_monitoring_window,
    source_timezone_name,
)
from app.modules.sources.oauth_service import build_gmail_oauth_start_for_source
from app.modules.sources.provider_sources import (
    CANVAS_ICS_DISPLAY_NAME,
    CANVAS_ICS_SOURCE_KEY,
    get_canvas_ics_source_for_user,
    get_gmail_source_for_user,
)
from app.modules.sources.source_runtime_state import derive_source_runtime_state
from app.modules.sources.source_secrets import decode_source_secrets
from app.modules.sources.schemas import InputSourcePatchRequest
from app.modules.sources.source_serializers import serialize_source
from app.modules.sources.sources_service import update_input_source


class OnboardingRegisterError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 422,
        code: str = "onboarding_invalid_input",
        message_code: str | None = None,
        message_params: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message_code = message_code or code
        self.message_params = message_params or {}


@dataclass(frozen=True)
class SourceHealthSummary:
    status: str
    message: str
    message_code: str
    message_params: dict
    affected_source_id: int | None
    affected_provider: str | None


@dataclass(frozen=True)
class OnboardingSourceSummary:
    source_id: int
    provider: str
    connected: bool
    has_monitoring_window: bool
    runtime_state: str
    oauth_account_email: str | None
    monitoring_window: SourceMonitoringWindow | None


@dataclass(frozen=True)
class OnboardingStatus:
    stage: str
    message: str
    message_code: str
    message_params: dict
    registered_user_id: int | None
    first_source_id: int | None
    source_health: SourceHealthSummary
    canvas_source: OnboardingSourceSummary | None
    gmail_source: OnboardingSourceSummary | None
    gmail_skipped: bool
    monitoring_window: SourceMonitoringWindow | None


@dataclass(frozen=True)
class OnboardingRegisterResult:
    user_id: int
    stage: str
    first_source_id: int | None


def get_onboarding_status_for_user(db: Session, *, user: User) -> OnboardingStatus:
    all_sources = list(
        db.scalars(
            select(InputSource)
            .where(InputSource.user_id == user.id)
            .order_by(InputSource.created_at.asc(), InputSource.id.asc())
        ).all()
    )
    active_sources = [source for source in all_sources if source.is_active]
    first_error_source = next((source for source in active_sources if source.last_error_message), None)
    source_health = _derive_source_health(active_sources=active_sources, first_error_source=first_error_source)

    canvas_source = get_canvas_ics_source_for_user(db, user_id=user.id)
    gmail_source = get_gmail_source_for_user(db, user_id=user.id)
    canvas_summary = _build_onboarding_source_summary(db, source=canvas_source)
    gmail_summary = _build_onboarding_source_summary(db, source=gmail_source)
    gmail_skipped = user.gmail_onboarding_skipped_at is not None
    first_source_id = all_sources[0].id if all_sources else None
    monitoring_window = _preferred_monitoring_window(canvas_summary=canvas_summary, gmail_summary=gmail_summary)

    stage, message, message_code, message_params = _derive_stage_and_message(
        user=user,
        canvas_source=canvas_summary,
        gmail_source=gmail_summary,
        gmail_skipped=gmail_skipped,
    )

    return OnboardingStatus(
        stage=stage,
        message=message,
        message_code=message_code,
        message_params=message_params,
        registered_user_id=user.id,
        first_source_id=first_source_id,
        source_health=source_health,
        canvas_source=canvas_summary,
        gmail_source=gmail_summary,
        gmail_skipped=gmail_skipped,
        monitoring_window=monitoring_window,
    )


def get_onboarding_status(db: Session, *, user: User) -> OnboardingStatus:
    return get_onboarding_status_for_user(db, user=user)


def register_onboarding(
    db: Session,
    *,
    user: User,
    email: str,
) -> OnboardingRegisterResult:
    normalized = email.strip().lower()
    if normalized != user.email.strip().lower():
        raise OnboardingRegisterError(
            "email is managed by auth register flow",
            status_code=422,
            code="onboarding_email_managed_by_auth",
            message_code="onboarding.email_managed_by_auth",
        )

    status = get_onboarding_status_for_user(db, user=user)
    return OnboardingRegisterResult(
        user_id=user.id,
        stage=status.stage,
        first_source_id=status.first_source_id,
    )


def upsert_onboarding_canvas_ics(
    db: Session,
    *,
    user: User,
    url: str,
) -> OnboardingStatus:
    source = get_canvas_ics_source_for_user(db, user_id=user.id)
    if source is None:
        source = InputSource(
            user_id=user.id,
            source_kind=SourceKind.CALENDAR,
            provider="ics",
            source_key=CANVAS_ICS_SOURCE_KEY,
            display_name=CANVAS_ICS_DISPLAY_NAME,
            is_active=False,
            poll_interval_seconds=900,
            next_poll_at=None,
        )
        db.add(source)
        db.flush()
        source.config = InputSourceConfig(source_id=source.id, schema_version=1, config_json={})
        source.cursor = InputSourceCursor(source_id=source.id, version=1, cursor_json={})
    if source.secrets is None:
        source.secrets = InputSourceSecret(
            source_id=source.id,
            encrypted_payload=encrypt_secret(json.dumps({"url": url}, separators=(",", ":"), ensure_ascii=True)),
        )
    else:
        source.secrets.encrypted_payload = encrypt_secret(json.dumps({"url": url}, separators=(",", ":"), ensure_ascii=True))

    current_term = parse_source_monitoring_window(source, required=False)
    if current_term is None:
        source.is_active = False
        source.next_poll_at = None
    db.commit()
    return get_onboarding_status_for_user(db, user=user)


def start_onboarding_gmail_oauth(
    db: Session,
    *,
    user: User,
    label_id: str | None = "INBOX",
    return_to: str = "onboarding",
) -> tuple[InputSource, str, datetime]:
    source = _ensure_onboarding_gmail_source(db, user=user, label_id=label_id)
    authorization_url, expires_at = build_gmail_oauth_start_for_source(db, source=source, return_to=return_to)
    return source, authorization_url, expires_at


def skip_onboarding_gmail(
    db: Session,
    *,
    user: User,
    now: datetime | None = None,
) -> OnboardingStatus:
    user.gmail_onboarding_skipped_at = now or datetime.now(timezone.utc)
    db.commit()
    return get_onboarding_status_for_user(db, user=user)


def apply_onboarding_monitoring_window(
    db: Session,
    *,
    user: User,
    monitor_since: str,
) -> OnboardingStatus:
    normalized_config = normalize_monitoring_window_config(
        config={"monitor_since": monitor_since},
        required=True,
    )
    monitoring_window = parse_monitoring_window_config(normalized_config, required=True)
    current = datetime.now(timezone.utc)

    canvas_source = get_canvas_ics_source_for_user(db, user_id=user.id)
    if canvas_source is None or not _source_has_canvas_url(canvas_source):
        raise OnboardingRegisterError(
            "Connect Canvas ICS before saving the monitoring window",
            status_code=409,
            code="onboarding_canvas_required_before_monitoring_window",
            message_code="onboarding.canvas_required_before_monitoring_window",
        )

    gmail_source = get_gmail_source_for_user(db, user_id=user.id)
    connected_sources = [canvas_source]
    if gmail_source is not None and _source_has_gmail_connection(gmail_source):
        connected_sources.append(gmail_source)

    user.onboarding_completed_at = current
    for source in connected_sources:
        requested_config = _merge_source_config_with_monitoring(source=source, window=monitoring_window)
        update_input_source(
            db,
            source=source,
            payload=InputSourcePatchRequest(
                is_active=True,
                config=requested_config,
            ),
        )

    db.refresh(user)
    return get_onboarding_status_for_user(db, user=user)


def _ensure_onboarding_gmail_source(
    db: Session,
    *,
    user: User,
    label_id: str | None,
) -> InputSource:
    normalized_label_id = (label_id or "INBOX").strip() or "INBOX"
    existing_binding = _preferred_monitoring_window(
        canvas_summary=_build_onboarding_source_summary(db, source=get_canvas_ics_source_for_user(db, user_id=user.id)),
        gmail_summary=None,
    )
    source = get_gmail_source_for_user(db, user_id=user.id)
    if source is None:
        config_json: dict[str, object] = {"label_id": normalized_label_id}
        if existing_binding is not None:
            config_json.update(existing_binding.to_config_json())
        source = InputSource(
            user_id=user.id,
            source_kind=SourceKind.EMAIL,
            provider="gmail",
            source_key="gmail_inbox",
            display_name="Gmail Inbox",
            is_active=existing_binding is not None,
            poll_interval_seconds=900,
            next_poll_at=existing_binding.monitor_start_at_utc(timezone_name=user.timezone_name) if existing_binding is not None else None,
        )
        db.add(source)
        db.flush()
        source.config = InputSourceConfig(source_id=source.id, schema_version=1, config_json=config_json)
        source.cursor = InputSourceCursor(source_id=source.id, version=1, cursor_json={})
    else:
        config_json = dict(source.config.config_json if source.config is not None else {})
        config_json["label_id"] = normalized_label_id
        if existing_binding is not None and parse_source_monitoring_window(source, required=False) is None:
            config_json.update(existing_binding.to_config_json())
        if source.config is None:
            source.config = InputSourceConfig(source_id=source.id, schema_version=1, config_json=config_json)
        else:
            source.config.config_json = config_json

    user.gmail_onboarding_skipped_at = None
    db.commit()
    db.refresh(source)
    return source


def _build_onboarding_source_summary(db: Session, *, source: InputSource | None) -> OnboardingSourceSummary | None:
    if source is None:
        return None
    runtime_state = derive_source_runtime_state(db, source=source)
    serialized = serialize_source(source, runtime_state=runtime_state)
    monitoring_window = parse_source_monitoring_window(source, required=False)
    return OnboardingSourceSummary(
        source_id=source.id,
        provider=source.provider,
        connected=_source_is_connected(source),
        has_monitoring_window=monitoring_window is not None,
        runtime_state=runtime_state.runtime_state,
        oauth_account_email=serialized.get("oauth_account_email"),
        monitoring_window=monitoring_window,
    )


def _preferred_monitoring_window(
    *,
    canvas_summary: OnboardingSourceSummary | None,
    gmail_summary: OnboardingSourceSummary | None,
) -> SourceMonitoringWindow | None:
    if canvas_summary is not None and canvas_summary.monitoring_window is not None:
        return canvas_summary.monitoring_window
    if gmail_summary is not None and gmail_summary.monitoring_window is not None:
        return gmail_summary.monitoring_window
    return None


def _derive_stage_and_message(
    *,
    user: User,
    canvas_source: OnboardingSourceSummary | None,
    gmail_source: OnboardingSourceSummary | None,
    gmail_skipped: bool,
) -> tuple[str, str, str, dict]:
    if canvas_source is None or not canvas_source.connected:
        return (
            "needs_canvas_ics",
            "Add your Canvas ICS link before anything else.",
            "onboarding.stage.needs_canvas_ics",
            {},
        )

    canvas_binding = canvas_source.monitoring_window
    gmail_connected = gmail_source is not None and gmail_source.connected
    connected_sources = [canvas_source]
    if gmail_connected and gmail_source is not None:
        connected_sources.append(gmail_source)

    if canvas_binding is None and not gmail_connected and not gmail_skipped:
        return (
            "needs_gmail_or_skip",
            "Connect Gmail now or skip it for this workspace.",
            "onboarding.stage.needs_gmail_or_skip",
            {},
        )

    if any(source.monitoring_window is None for source in connected_sources):
        return (
            "needs_monitoring_window",
            "Use the default 90-day monitoring window or choose an earlier start date before sync begins.",
            "onboarding.stage.needs_monitoring_window",
            {},
        )

    return "ready", "Onboarding complete.", "onboarding.stage.ready", {}


def _derive_source_health(*, active_sources: list[InputSource], first_error_source: InputSource | None) -> SourceHealthSummary:
    if not active_sources:
        return SourceHealthSummary(
            status="disconnected",
            message="No active sources connected yet.",
            message_code="onboarding.source_health.disconnected",
            message_params={},
            affected_source_id=None,
            affected_provider=None,
        )
    if first_error_source is not None:
        return SourceHealthSummary(
            status="attention",
            message="A connected source needs attention before syncs are reliable.",
            message_code="onboarding.source_health.attention",
            message_params={},
            affected_source_id=first_error_source.id,
            affected_provider=first_error_source.provider,
        )
    return SourceHealthSummary(
        status="healthy",
        message="Connected sources are ready for intake.",
        message_code="onboarding.source_health.healthy",
        message_params={},
        affected_source_id=None,
        affected_provider=None,
    )


def _source_is_connected(source: InputSource) -> bool:
    if source.provider == "ics":
        return _source_has_canvas_url(source)
    if source.provider == "gmail":
        return _source_has_gmail_connection(source)
    return source.is_active


def _source_has_canvas_url(source: InputSource) -> bool:
    payload = decode_source_secrets(source)
    url = payload.get("url")
    return isinstance(url, str) and bool(url.strip())


def _source_has_gmail_connection(source: InputSource) -> bool:
    payload = decode_source_secrets(source)
    account_email = payload.get("account_email")
    access_token = payload.get("access_token")
    return (
        isinstance(account_email, str)
        and bool(account_email.strip())
    ) or (
        isinstance(access_token, str)
        and bool(access_token.strip())
    )


def _merge_source_config_with_monitoring(*, source: InputSource, window: SourceMonitoringWindow) -> dict:
    config_json = dict(source.config.config_json if source.config is not None else {})
    config_json.update(window.to_config_json())
    return config_json


__all__ = [
    "OnboardingRegisterError",
    "OnboardingRegisterResult",
    "OnboardingSourceSummary",
    "OnboardingStatus",
    "SourceHealthSummary",
    "apply_onboarding_monitoring_window",
    "get_onboarding_status",
    "get_onboarding_status_for_user",
    "register_onboarding",
    "skip_onboarding_gmail",
    "start_onboarding_gmail_oauth",
    "upsert_onboarding_canvas_ics",
]
