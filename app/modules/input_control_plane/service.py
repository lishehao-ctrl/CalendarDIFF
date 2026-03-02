from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.events import new_event
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models import (
    IngestJob,
    IngestJobStatus,
    IngestApplyLog,
    IngestResult,
    IngestTriggerType,
    InputSource,
    InputSourceConfig,
    InputSourceCursor,
    InputSourceSecret,
    IntegrationOutbox,
    OutboxStatus,
    SourceKind,
    SyncRequest,
    SyncRequestStatus,
    User,
)
from app.modules.input_control_plane.schemas import (
    InputSourceCreateRequest,
    InputSourcePatchRequest,
)
from app.modules.sync.gmail_client import GmailClient

GMAIL_OAUTH_STATE_TTL_MINUTES = 10


def list_input_sources(db: Session, *, user_id: int) -> list[InputSource]:
    return db.scalars(
        select(InputSource)
        .where(InputSource.user_id == user_id)
        .order_by(InputSource.created_at.desc(), InputSource.id.desc())
    ).all()


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


def enqueue_sync_request(
    db: Session,
    *,
    source: InputSource,
    trigger_type: IngestTriggerType,
    idempotency_key: str,
    metadata: dict | None = None,
    trace_id: str | None = None,
) -> SyncRequest:
    request_id = uuid4().hex
    row = SyncRequest(
        request_id=request_id,
        source_id=source.id,
        trigger_type=trigger_type,
        status=SyncRequestStatus.PENDING,
        idempotency_key=idempotency_key[:255],
        trace_id=trace_id,
        metadata_json=metadata or {},
    )
    db.add(row)
    db.flush()
    _append_outbox_event(
        db,
        event_type="sync.requested",
        aggregate_type="sync_request",
        aggregate_id=request_id,
        payload={
            "request_id": request_id,
            "source_id": source.id,
            "trigger_type": trigger_type.value,
            "provider": source.provider,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def enqueue_sync_request_idempotent(
    db: Session,
    *,
    source: InputSource,
    trigger_type: IngestTriggerType,
    idempotency_key: str,
    metadata: dict | None = None,
    trace_id: str | None = None,
) -> SyncRequest:
    try:
        return enqueue_sync_request(
            db,
            source=source,
            trigger_type=trigger_type,
            idempotency_key=idempotency_key,
            metadata=metadata,
            trace_id=trace_id,
        )
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(SyncRequest).where(
                SyncRequest.source_id == source.id,
                SyncRequest.idempotency_key == idempotency_key[:255],
            )
        )
        if existing is None:
            raise
        return existing


def get_sync_request_status(db: Session, *, request_id: str) -> SyncRequest | None:
    return db.scalar(select(SyncRequest).where(SyncRequest.request_id == request_id))


def build_gmail_oauth_start_for_source(
    db: Session,
    *,
    source: InputSource,
    now: datetime | None = None,
    gmail_client: GmailClient | None = None,
) -> tuple[str, datetime]:
    current = now or datetime.now(timezone.utc)
    expires_at = current + timedelta(minutes=GMAIL_OAUTH_STATE_TTL_MINUTES)
    state_payload = {
        "source_id": source.id,
        "provider": source.provider,
        "exp": expires_at.isoformat(),
    }
    state_token = encrypt_secret(json.dumps(state_payload, separators=(",", ":"), ensure_ascii=True))
    client = gmail_client or GmailClient()
    return client.build_authorization_url(state=state_token), expires_at


def handle_gmail_oauth_callback(
    db: Session,
    *,
    code: str,
    state: str,
    now: datetime | None = None,
    gmail_client: GmailClient | None = None,
) -> tuple[InputSource, SyncRequest]:
    current = now or datetime.now(timezone.utc)
    state_payload = _parse_oauth_state(state)
    source_id = int(state_payload["source_id"])
    provider = str(state_payload["provider"])
    if provider != "gmail":
        raise RuntimeError("Unsupported oauth provider in state payload")
    expires_raw = state_payload.get("exp")
    if not isinstance(expires_raw, str):
        raise RuntimeError("OAuth state missing expiration")
    expires_at = datetime.fromisoformat(expires_raw)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    else:
        expires_at = expires_at.astimezone(timezone.utc)
    if current > expires_at:
        raise RuntimeError("OAuth state expired")

    source = db.get(InputSource, source_id)
    if source is None or source.provider != "gmail":
        raise RuntimeError("Input source not found for oauth callback")

    client = gmail_client or GmailClient()
    tokens = client.exchange_code(code=code)
    profile = client.get_profile(access_token=tokens.access_token)

    merged_payload = {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "expires_at": tokens.expires_at.isoformat() if tokens.expires_at is not None else None,
        "account_email": profile.email_address,
        "history_id": profile.history_id,
    }
    encrypted_payload = encrypt_secret(json.dumps(merged_payload, separators=(",", ":"), ensure_ascii=True))
    if source.secrets is None:
        source.secrets = InputSourceSecret(source_id=source.id, encrypted_payload=encrypted_payload)
    else:
        source.secrets.encrypted_payload = encrypted_payload

    if source.cursor is None:
        source.cursor = InputSourceCursor(source_id=source.id, version=1, cursor_json={})
    source.cursor.cursor_json = {"history_id": profile.history_id}

    request = enqueue_sync_request_idempotent(
        db,
        source=source,
        trigger_type=IngestTriggerType.MANUAL,
        idempotency_key=f"oauth:init:{source.id}",
        metadata={"reason": "oauth_callback"},
    )
    return source, request


def build_sync_request_status_payload(db: Session, *, sync_request: SyncRequest) -> dict:
    result = db.scalar(select(IngestResult).where(IngestResult.request_id == sync_request.request_id))
    apply_log = db.scalar(select(IngestApplyLog).where(IngestApplyLog.request_id == sync_request.request_id))
    connector_result: dict | None = None
    if result is not None:
        connector_result = {
            "provider": result.provider,
            "status": result.status.value,
            "fetched_at": result.fetched_at,
            "error_code": result.error_code,
            "error_message": result.error_message,
            "records_count": len(result.records or []),
        }
    return {
        "request_id": sync_request.request_id,
        "source_id": sync_request.source_id,
        "trigger_type": sync_request.trigger_type.value,
        "status": sync_request.status.value,
        "idempotency_key": sync_request.idempotency_key,
        "trace_id": sync_request.trace_id,
        "error_code": sync_request.error_code,
        "error_message": sync_request.error_message,
        "metadata": sync_request.metadata_json or {},
        "created_at": sync_request.created_at,
        "updated_at": sync_request.updated_at,
        "connector_result": connector_result,
        "applied": apply_log is not None,
        "applied_at": apply_log.applied_at if apply_log is not None else None,
    }


def replay_ingest_job(db: Session, *, job_id: int) -> IngestJob:
    now = datetime.now(timezone.utc)
    job = db.get(IngestJob, job_id)
    if job is None:
        raise RuntimeError("ingest job not found")
    if job.status != IngestJobStatus.DEAD_LETTER:
        raise RuntimeError("ingest job is not dead-lettered")
    job.status = IngestJobStatus.PENDING
    job.next_retry_at = now
    job.dead_lettered_at = None
    job.claimed_by = None
    job.claim_token = None
    sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == job.request_id))
    if sync_request is not None:
        sync_request.status = SyncRequestStatus.QUEUED
        sync_request.error_code = None
        sync_request.error_message = None
    db.commit()
    db.refresh(job)
    return job


def replay_dead_letter_jobs(db: Session, *, limit: int = 100) -> list[IngestJob]:
    now = datetime.now(timezone.utc)
    capped_limit = max(1, min(limit, 500))
    jobs = db.scalars(
        select(IngestJob)
        .where(IngestJob.status == IngestJobStatus.DEAD_LETTER)
        .order_by(IngestJob.dead_lettered_at.asc().nullslast(), IngestJob.id.asc())
        .limit(capped_limit)
    ).all()
    if not jobs:
        return []
    for job in jobs:
        job.status = IngestJobStatus.PENDING
        job.next_retry_at = now
        job.dead_lettered_at = None
        job.claimed_by = None
        job.claim_token = None
        sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == job.request_id))
        if sync_request is not None:
            sync_request.status = SyncRequestStatus.QUEUED
            sync_request.error_code = None
            sync_request.error_message = None
    db.commit()
    for job in jobs:
        db.refresh(job)
    return jobs


def decode_source_secrets(source: InputSource) -> dict:
    if source.secrets is None:
        return {}
    try:
        raw = decrypt_secret(source.secrets.encrypted_payload)
        parsed = json.loads(raw)
    except Exception:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def serialize_source(source: InputSource) -> dict:
    return {
        "source_id": source.id,
        "user_id": source.user_id,
        "source_kind": source.source_kind.value,
        "provider": source.provider,
        "source_key": source.source_key,
        "display_name": source.display_name,
        "is_active": source.is_active,
        "poll_interval_seconds": source.poll_interval_seconds,
        "last_polled_at": source.last_polled_at,
        "next_poll_at": source.next_poll_at,
        "last_error_code": source.last_error_code,
        "last_error_message": source.last_error_message,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
        "config": source.config.config_json if source.config is not None else {},
    }


def _append_outbox_event(
    db: Session,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict,
) -> None:
    event = new_event(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
    )
    db.add(
        IntegrationOutbox(
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload_json=event.payload,
            status=OutboxStatus.PENDING,
            available_at=event.available_at,
        )
    )


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


def _parse_oauth_state(state_token: str) -> dict:
    try:
        decoded = decrypt_secret(state_token)
        parsed = json.loads(decoded)
    except Exception as exc:
        raise RuntimeError("Invalid OAuth state") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Invalid OAuth state payload")
    return parsed
