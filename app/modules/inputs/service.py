from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models import (
    Input,
    InputType,
    SyncRun,
    SyncRunStatus,
    SyncTriggerType,
)
from app.modules.inputs.schemas import InputCreateRequest
from app.modules.scheduler.runner import release_input_lock, try_acquire_input_lock
from app.modules.sync.gmail_client import GmailClient
from app.modules.sync.service import (
    LOCK_SKIPPED_COOLDOWN_SECONDS,
    SyncRunResult,
    record_lock_skipped_run,
    sync_input,
)

MANUAL_SYNC_RETRY_AFTER_SECONDS = 10
GMAIL_OAUTH_STATE_TTL_MINUTES = 10
FIXED_INPUT_INTERVAL_MINUTES = 15


@dataclass(frozen=True)
class InputCreateResult:
    input: Input
    upserted_existing: bool


@dataclass(frozen=True)
class GmailOAuthStartResult:
    authorization_url: str
    expires_at: datetime


@dataclass(frozen=True)
class GmailOAuthStatePayload:
    label: str | None
    from_contains: str | None
    subject_keywords: list[str] | None
    expires_at: datetime


class InputBusyError(RuntimeError):
    """Raised when manual sync cannot acquire input lock immediately."""

    def __init__(self, *, input_id: int, retry_after_seconds: int) -> None:
        self.input_id = input_id
        self.retry_after_seconds = retry_after_seconds
        super().__init__("another instance is syncing this input")


class InputDeactivateError(RuntimeError):
    """Raised when input deactivation violates runtime invariants."""

    def __init__(self, *, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class GmailOAuthStateError(RuntimeError):
    """Raised when Gmail OAuth state is invalid or expired."""


def build_gmail_oauth_start(
    *,
    label: str | None,
    from_contains: str | None,
    subject_keywords: list[str] | None,
    now: datetime | None = None,
    gmail_client: GmailClient | None = None,
) -> GmailOAuthStartResult:
    current = now or datetime.now(timezone.utc)
    expires_at = current + timedelta(minutes=GMAIL_OAUTH_STATE_TTL_MINUTES)
    state_payload: dict[str, object] = {
        "label": _normalize_optional_text(label),
        "from_contains": _normalize_optional_text(from_contains),
        "subject_keywords": _normalize_subject_keywords(subject_keywords),
        "exp": expires_at.isoformat(),
    }
    state_token = encrypt_secret(json.dumps(state_payload, separators=(",", ":")))
    client = gmail_client or GmailClient()
    authorization_url = client.build_authorization_url(state=state_token)
    return GmailOAuthStartResult(authorization_url=authorization_url, expires_at=expires_at)


def parse_gmail_oauth_state(state_token: str, *, now: datetime | None = None) -> GmailOAuthStatePayload:
    current = now or datetime.now(timezone.utc)
    try:
        decoded = decrypt_secret(state_token)
        payload = json.loads(decoded)
    except Exception as exc:
        raise GmailOAuthStateError("Invalid OAuth state") from exc

    if not isinstance(payload, dict):
        raise GmailOAuthStateError("Invalid OAuth state payload")

    label = payload.get("label")
    if label is not None and not isinstance(label, str):
        raise GmailOAuthStateError("OAuth state contains invalid label")
    from_contains = payload.get("from_contains")
    if from_contains is not None and not isinstance(from_contains, str):
        raise GmailOAuthStateError("OAuth state contains invalid from_contains")

    raw_keywords = payload.get("subject_keywords")
    subject_keywords: list[str] | None
    if raw_keywords is None:
        subject_keywords = None
    elif isinstance(raw_keywords, list) and all(isinstance(item, str) for item in raw_keywords):
        subject_keywords = _normalize_subject_keywords(raw_keywords)
    else:
        raise GmailOAuthStateError("OAuth state contains invalid subject_keywords")

    exp_raw = payload.get("exp")
    if not isinstance(exp_raw, str):
        raise GmailOAuthStateError("OAuth state missing expiration")
    try:
        expires_at = datetime.fromisoformat(exp_raw)
    except Exception as exc:
        raise GmailOAuthStateError("OAuth state has invalid expiration") from exc
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    else:
        expires_at = expires_at.astimezone(timezone.utc)
    if current > expires_at:
        raise GmailOAuthStateError("OAuth state expired")

    return GmailOAuthStatePayload(
        label=_normalize_optional_text(label),
        from_contains=_normalize_optional_text(from_contains),
        subject_keywords=subject_keywords,
        expires_at=expires_at,
    )


def create_ics_input(
    db: Session,
    *,
    user_id: int,
    payload: InputCreateRequest,
) -> InputCreateResult:
    canonical_url = _canonicalize_ics_url(str(payload.url))
    identity_key = _build_ics_identity_key(canonical_url)
    encrypted_url = encrypt_secret(canonical_url)
    interval_minutes = FIXED_INPUT_INTERVAL_MINUTES

    def _insert_new_ics_input() -> Input:
        row = Input(
            user_id=user_id,
            type=InputType.ICS,
            provider=None,
            identity_key=identity_key,
            encrypted_url=encrypted_url,
            notify_email=None,
            interval_minutes=interval_minutes,
            is_active=True,
        )
        db.add(row)
        db.flush()
        return row

    existing_input = db.scalar(
        select(Input)
        .where(
            Input.user_id == user_id,
            Input.type == InputType.ICS,
        )
        .with_for_update()
    )
    if existing_input is not None and existing_input.identity_key == identity_key:
        existing_input.encrypted_url = encrypted_url
        existing_input.notify_email = None
        existing_input.interval_minutes = interval_minutes
        existing_input.is_active = True
        db.commit()
        db.refresh(existing_input)
        return InputCreateResult(input=existing_input, upserted_existing=True)

    if existing_input is not None:
        # Single-ICS invariant: replacing URL deletes previous ICS timeline lineage.
        db.delete(existing_input)
        db.flush()

    input_row = _insert_new_ics_input()
    try:
        db.commit()
        db.refresh(input_row)
        return InputCreateResult(input=input_row, upserted_existing=False)
    except IntegrityError:
        db.rollback()
        existing_input = db.scalar(
            select(Input)
            .where(
                Input.user_id == user_id,
                Input.type == InputType.ICS,
            )
            .with_for_update()
        )
        if existing_input is not None and existing_input.identity_key == identity_key:
            existing_input.encrypted_url = encrypted_url
            existing_input.notify_email = None
            existing_input.interval_minutes = interval_minutes
            existing_input.is_active = True
            db.commit()
            db.refresh(existing_input)
            return InputCreateResult(input=existing_input, upserted_existing=True)

        if existing_input is not None:
            db.delete(existing_input)
            db.flush()

        retry_row = _insert_new_ics_input()
        try:
            db.commit()
            db.refresh(retry_row)
            return InputCreateResult(input=retry_row, upserted_existing=False)
        except IntegrityError:
            db.rollback()
            latest = db.scalar(
                select(Input)
                .where(
                    Input.user_id == user_id,
                    Input.type == InputType.ICS,
                )
                .order_by(Input.created_at.desc(), Input.id.desc())
                .limit(1)
            )
            if latest is None:
                raise
            db.refresh(latest)
            return InputCreateResult(input=latest, upserted_existing=(latest.identity_key == identity_key))


def create_gmail_input_from_oauth(
    db: Session,
    *,
    user_id: int,
    label: str | None,
    from_contains: str | None,
    subject_keywords: list[str] | None,
    account_email: str,
    history_id: str | None,
    access_token: str,
    refresh_token: str | None,
    access_token_expires_at: datetime | None,
) -> InputCreateResult:
    account_email_norm = account_email.strip().lower()
    label_norm = _normalize_optional_text(label)
    from_norm = _normalize_optional_text(from_contains)
    keywords_norm = _normalize_subject_keywords(subject_keywords)
    identity_key = _build_gmail_identity_key(
        account_email=account_email_norm,
        label=label_norm,
        from_contains=from_norm,
        subject_keywords=keywords_norm,
    )

    encrypted_url = encrypt_secret("email://gmail")
    encrypted_access_token = encrypt_secret(access_token)
    refresh_token_normalized = refresh_token.strip() if isinstance(refresh_token, str) else None
    if refresh_token_normalized == "":
        refresh_token_normalized = None
    encrypted_refresh_token = encrypt_secret(refresh_token_normalized) if refresh_token_normalized else None
    applied_interval = FIXED_INPUT_INTERVAL_MINUTES

    existing_input = db.scalar(
        select(Input)
        .where(
            Input.user_id == user_id,
            Input.type == InputType.EMAIL,
            Input.identity_key == identity_key,
        )
        .with_for_update()
    )
    if existing_input is not None:
        existing_input.provider = "gmail"
        existing_input.encrypted_url = encrypted_url
        existing_input.notify_email = None
        existing_input.interval_minutes = applied_interval
        existing_input.is_active = True
        existing_input.gmail_label = label_norm
        existing_input.gmail_from_contains = from_norm
        existing_input.gmail_subject_keywords = keywords_norm
        if existing_input.gmail_history_id is None and history_id is not None:
            existing_input.gmail_history_id = history_id
        existing_input.gmail_account_email = account_email_norm
        existing_input.encrypted_access_token = encrypted_access_token
        if encrypted_refresh_token is not None:
            existing_input.encrypted_refresh_token = encrypted_refresh_token
        elif existing_input.encrypted_refresh_token is None:
            raise RuntimeError("Missing Gmail refresh token")
        existing_input.access_token_expires_at = access_token_expires_at
        db.commit()
        db.refresh(existing_input)
        return InputCreateResult(input=existing_input, upserted_existing=True)

    if encrypted_refresh_token is None:
        raise RuntimeError("Missing Gmail refresh token")

    input = Input(
        user_id=user_id,
        type=InputType.EMAIL,
        provider="gmail",
        identity_key=identity_key,
        encrypted_url=encrypted_url,
        notify_email=None,
        interval_minutes=applied_interval,
        is_active=True,
        gmail_label=label_norm,
        gmail_from_contains=from_norm,
        gmail_subject_keywords=keywords_norm,
        gmail_history_id=history_id,
        gmail_account_email=account_email_norm,
        encrypted_access_token=encrypted_access_token,
        encrypted_refresh_token=encrypted_refresh_token,
        access_token_expires_at=access_token_expires_at,
    )
    db.add(input)
    try:
        db.commit()
        db.refresh(input)
        return InputCreateResult(input=input, upserted_existing=False)
    except IntegrityError:
        db.rollback()
        existing_input = db.scalar(
            select(Input)
            .where(
                Input.user_id == user_id,
                Input.type == InputType.EMAIL,
                Input.identity_key == identity_key,
            )
            .with_for_update()
        )
        if existing_input is None:
            raise
        existing_input.provider = "gmail"
        existing_input.encrypted_url = encrypted_url
        existing_input.notify_email = None
        existing_input.interval_minutes = applied_interval
        existing_input.is_active = True
        existing_input.gmail_label = label_norm
        existing_input.gmail_from_contains = from_norm
        existing_input.gmail_subject_keywords = keywords_norm
        if existing_input.gmail_history_id is None and history_id is not None:
            existing_input.gmail_history_id = history_id
        existing_input.gmail_account_email = account_email_norm
        existing_input.encrypted_access_token = encrypted_access_token
        if encrypted_refresh_token is not None:
            existing_input.encrypted_refresh_token = encrypted_refresh_token
        elif existing_input.encrypted_refresh_token is None:
            raise RuntimeError("Missing Gmail refresh token")
        existing_input.access_token_expires_at = access_token_expires_at
        db.commit()
        db.refresh(existing_input)
        return InputCreateResult(input=existing_input, upserted_existing=True)


def list_inputs(db: Session) -> list[Input]:
    return db.scalars(select(Input).order_by(Input.id.asc())).all()


def list_inputs_with_runtime_state(
    db: Session,
    *,
    now: datetime | None = None,
    user_id: int | None = None,
) -> list[tuple[Input, datetime | None, str | None]]:
    current = now or datetime.now(timezone.utc)
    next_check_expr = func.coalesce(
        Input.last_checked_at + func.make_interval(0, 0, 0, 0, 0, Input.interval_minutes, 0),
        current,
    ).label("next_check_at")

    latest_run_subquery = (
        select(
            SyncRun.input_id.label("input_id"),
            func.max(SyncRun.id).label("latest_run_id"),
        )
        .group_by(SyncRun.input_id)
        .subquery()
    )

    stmt = (
        select(Input, next_check_expr, SyncRun.status, SyncRun.trigger_type, SyncRun.started_at)
        .outerjoin(latest_run_subquery, latest_run_subquery.c.input_id == Input.id)
        .outerjoin(SyncRun, SyncRun.id == latest_run_subquery.c.latest_run_id)
    )
    if user_id is not None:
        stmt = stmt.where(Input.user_id == user_id)
    stmt = stmt.order_by(Input.id.asc())

    rows = db.execute(stmt).all()
    cooldown_window = timedelta(seconds=LOCK_SKIPPED_COOLDOWN_SECONDS)
    normalized_rows: list[tuple[Input, datetime | None, str | None]] = []
    for input, next_check_at, status, trigger_type, started_at in rows:
        adjusted_next_check_at = next_check_at
        if (
            status == SyncRunStatus.LOCK_SKIPPED
            and trigger_type == SyncTriggerType.SCHEDULER
            and started_at is not None
        ):
            cooldown_until = started_at + cooldown_window
            if adjusted_next_check_at is None or cooldown_until > adjusted_next_check_at:
                adjusted_next_check_at = cooldown_until
        normalized_rows.append((input, adjusted_next_check_at, status.value if status is not None else None))
    return normalized_rows


def list_latest_run_status_map(db: Session, input_ids: list[int]) -> dict[int, str]:
    if not input_ids:
        return {}

    latest_run_subquery = (
        select(
            SyncRun.input_id.label("input_id"),
            func.max(SyncRun.id).label("latest_run_id"),
        )
        .where(SyncRun.input_id.in_(input_ids))
        .group_by(SyncRun.input_id)
        .subquery()
    )

    rows = db.execute(
        select(SyncRun.input_id, SyncRun.status).join(
            latest_run_subquery, SyncRun.id == latest_run_subquery.c.latest_run_id
        )
    ).all()
    return {input_id: status.value for input_id, status in rows}


def get_input_by_id(db: Session, input_id: int) -> Input | None:
    return db.get(Input, input_id)


def deactivate_input(db: Session, input: Input) -> bool:
    if not input.is_active:
        return False

    if input.type == InputType.ICS:
        active_ics_count = db.scalar(
            select(func.count(Input.id)).where(
                Input.user_id == input.user_id,
                Input.type == InputType.ICS,
                Input.is_active.is_(True),
            )
        )
        if int(active_ics_count or 0) <= 1:
            raise InputDeactivateError(
                code="cannot_deactivate_primary_ics",
                message="Cannot deactivate the only active ICS input",
            )

    input.is_active = False
    db.commit()
    db.refresh(input)
    return True


def run_manual_input_sync(db: Session, input: Input) -> SyncRunResult:
    settings = get_settings()
    lock_acquired = try_acquire_input_lock(db, settings.input_lock_namespace, input.id)
    if not lock_acquired:
        record_lock_skipped_run(
            db=db,
            input_id=input.id,
            trigger_type=SyncTriggerType.MANUAL,
        )
        raise InputBusyError(
            input_id=input.id,
            retry_after_seconds=MANUAL_SYNC_RETRY_AFTER_SECONDS,
        )

    try:
        return sync_input(
            db=db,
            input=input,
            trigger_type=SyncTriggerType.MANUAL,
        )
    finally:
        release_input_lock(db, settings.input_lock_namespace, input.id)


def _canonicalize_ics_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url.strip())
    canonical = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    return canonical


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_subject_keywords(value: list[str] | None) -> list[str] | None:
    if not value:
        return None
    cleaned = sorted({item.strip().lower() for item in value if item and item.strip()})
    return cleaned or None


def _build_ics_identity_key(canonical_url: str) -> str:
    return sha256(f"ics|{canonical_url}".encode("utf-8")).hexdigest()


def _build_gmail_identity_key(
    *,
    account_email: str,
    label: str | None,
    from_contains: str | None,
    subject_keywords: list[str] | None,
) -> str:
    payload = {
        "account_email": account_email,
        "label": label,
        "from_contains": from_contains,
        "subject_keywords": subject_keywords or [],
    }
    return sha256(f"gmail|{json.dumps(payload, sort_keys=True, separators=(',', ':'))}".encode("utf-8")).hexdigest()
