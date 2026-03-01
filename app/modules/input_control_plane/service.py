from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.contracts.events import new_event
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models import (
    LlmApiMode,
    LlmProvider,
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
    SourceLlmBinding,
    SourceKind,
    SyncRequest,
    SyncRequestStatus,
    User,
)
from app.modules.input_control_plane.schemas import (
    InputSourceCreateRequest,
    InputSourcePatchRequest,
    LlmProviderCreateRequest,
    LlmProviderPatchRequest,
    SourceLlmBindingCreateRequest,
    SourceLlmBindingPatchRequest,
)
from app.modules.llm_gateway.contracts import LlmGatewayError, LlmInvokeRequest
from app.modules.llm_gateway.gateway import invoke_llm_json
from app.modules.llm_gateway.registry import clear_llm_registry_cache
from app.modules.llm_gateway.transport_openai_compat import build_openai_compat_endpoint
from app.modules.sync.gmail_client import GmailClient

GMAIL_OAUTH_STATE_TTL_MINUTES = 10


def list_input_sources(db: Session, *, user_id: int) -> list[InputSource]:
    return db.scalars(
        select(InputSource)
        .options(
            joinedload(InputSource.config),
            joinedload(InputSource.llm_binding).joinedload(SourceLlmBinding.provider),
        )
        .where(InputSource.user_id == user_id)
        .order_by(InputSource.created_at.desc(), InputSource.id.desc())
    ).all()


def get_input_source(db: Session, *, user_id: int, source_id: int) -> InputSource | None:
    return db.scalar(
        select(InputSource)
        .options(
            joinedload(InputSource.config),
            joinedload(InputSource.llm_binding).joinedload(SourceLlmBinding.provider),
        )
        .where(
            InputSource.id == source_id,
            InputSource.user_id == user_id,
        )
    )


def list_llm_providers(db: Session) -> list[LlmProvider]:
    return db.scalars(
        select(LlmProvider)
        .order_by(LlmProvider.created_at.desc(), LlmProvider.id.desc())
    ).all()


def get_llm_provider(db: Session, *, provider_id: str) -> LlmProvider | None:
    return db.scalar(select(LlmProvider).where(LlmProvider.provider_id == provider_id.strip()))


def create_llm_provider(db: Session, *, payload: LlmProviderCreateRequest) -> LlmProvider:
    if payload.is_default and not payload.enabled:
        raise RuntimeError("default llm provider must be enabled")
    if payload.is_default:
        _clear_default_provider(db)
    provider = LlmProvider(
        provider_id=payload.provider_id.strip(),
        name=payload.name.strip(),
        vendor=payload.vendor.strip().lower(),
        base_url=payload.base_url.strip(),
        api_mode=LlmApiMode(payload.api_mode),
        model=payload.model.strip(),
        api_key_ref=payload.api_key_ref.strip(),
        timeout_seconds=payload.timeout_seconds,
        max_retries=payload.max_retries,
        max_input_chars=payload.max_input_chars,
        enabled=payload.enabled,
        is_default=payload.is_default,
        extra_json=dict(payload.extra_config),
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    clear_llm_registry_cache()
    return provider


def update_llm_provider(
    db: Session,
    *,
    provider: LlmProvider,
    payload: LlmProviderPatchRequest,
) -> LlmProvider:
    if payload.name is not None:
        provider.name = payload.name.strip()
    if payload.vendor is not None:
        provider.vendor = payload.vendor.strip().lower()
    if payload.base_url is not None:
        provider.base_url = payload.base_url.strip()
    if payload.api_mode is not None:
        provider.api_mode = LlmApiMode(payload.api_mode)
    if payload.model is not None:
        provider.model = payload.model.strip()
    if payload.api_key_ref is not None:
        provider.api_key_ref = payload.api_key_ref.strip()
    if payload.timeout_seconds is not None:
        provider.timeout_seconds = payload.timeout_seconds
    if payload.max_retries is not None:
        provider.max_retries = payload.max_retries
    if payload.max_input_chars is not None:
        provider.max_input_chars = payload.max_input_chars
    if payload.enabled is not None:
        provider.enabled = payload.enabled
    if payload.extra_config is not None:
        provider.extra_json = dict(payload.extra_config)
    if payload.is_default is not None:
        if payload.is_default:
            if payload.enabled is False or not provider.enabled:
                raise RuntimeError("default llm provider must be enabled")
            _clear_default_provider(db)
            provider.is_default = True
        else:
            provider.is_default = False
    db.commit()
    db.refresh(provider)
    clear_llm_registry_cache()
    return provider


def set_default_llm_provider(db: Session, *, provider: LlmProvider) -> LlmProvider:
    if not provider.enabled:
        raise RuntimeError("cannot set disabled llm provider as default")
    _clear_default_provider(db)
    provider.is_default = True
    db.commit()
    db.refresh(provider)
    clear_llm_registry_cache()
    return provider


def upsert_source_llm_binding(
    db: Session,
    *,
    source: InputSource,
    payload: SourceLlmBindingCreateRequest | SourceLlmBindingPatchRequest,
) -> SourceLlmBinding:
    provider: LlmProvider | None = None
    provider_id = payload.provider_id.strip() if payload.provider_id is not None else None
    if provider_id:
        provider = db.scalar(select(LlmProvider).where(LlmProvider.provider_id == provider_id))
        if provider is None:
            raise RuntimeError(f"llm provider not found: {provider_id}")
    elif source.llm_binding is None:
        raise RuntimeError("llm provider_id is required when creating source llm binding")

    if source.llm_binding is None:
        assert provider is not None
        source.llm_binding = SourceLlmBinding(
            source_id=source.id,
            llm_provider_id=provider.id,
            model_override=_normalize_optional_text(payload.model_override),
            api_mode_override=_normalize_optional_api_mode(payload.api_mode_override),
            prompt_profile=_normalize_optional_text(payload.prompt_profile),
            enabled=True if getattr(payload, "enabled", None) is None else bool(payload.enabled),
        )
    else:
        if provider is not None:
            source.llm_binding.llm_provider_id = provider.id
        if payload.model_override is not None:
            source.llm_binding.model_override = _normalize_optional_text(payload.model_override)
        if payload.api_mode_override is not None:
            source.llm_binding.api_mode_override = _normalize_optional_api_mode(payload.api_mode_override)
        if payload.prompt_profile is not None:
            source.llm_binding.prompt_profile = _normalize_optional_text(payload.prompt_profile)
        if getattr(payload, "enabled", None) is not None:
            source.llm_binding.enabled = bool(payload.enabled)
    db.flush()
    clear_llm_registry_cache()
    return source.llm_binding


def validate_llm_provider(db: Session, *, provider: LlmProvider) -> dict:
    endpoint = build_openai_compat_endpoint(
        base_url=provider.base_url,
        api_mode=provider.api_mode.value,
    )
    try:
        result = invoke_llm_json(
            db,
            invoke_request=LlmInvokeRequest(
                task_name="provider_validation",
                system_prompt="Return JSON object {'ok': true} only.",
                user_payload={"probe": "healthcheck"},
                output_schema_name="provider_validation",
                output_schema_json={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                    "additionalProperties": True,
                },
                llm_provider_id=provider.provider_id,
                source_provider="system",
                request_id=f"validate:{provider.provider_id}",
            ),
        )
        return {
            "provider_id": provider.provider_id,
            "api_mode": provider.api_mode.value,
            "endpoint": endpoint,
            "ok": True,
            "latency_ms": result.latency_ms,
            "error_code": None,
            "error_message": None,
        }
    except LlmGatewayError as exc:
        return {
            "provider_id": provider.provider_id,
            "api_mode": provider.api_mode.value,
            "endpoint": endpoint,
            "ok": False,
            "latency_ms": None,
            "error_code": exc.code,
            "error_message": str(exc),
        }


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
    if payload.llm_binding is not None:
        upsert_source_llm_binding(db, source=source, payload=payload.llm_binding)

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
    if payload.llm_binding is not None:
        upsert_source_llm_binding(db, source=source, payload=payload.llm_binding)
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
        "llm_binding": _serialize_source_llm_binding(source.llm_binding),
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


def _normalize_optional_api_mode(value: str | None) -> LlmApiMode | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return LlmApiMode(stripped)


def _serialize_source_llm_binding(binding: SourceLlmBinding | None) -> dict | None:
    if binding is None or binding.provider is None:
        return None
    provider = binding.provider
    model = binding.model_override or provider.model
    api_mode = binding.api_mode_override or provider.api_mode
    return {
        "provider_id": provider.provider_id,
        "provider_name": provider.name,
        "vendor": provider.vendor,
        "api_mode": api_mode.value,
        "model": model,
        "model_override": binding.model_override,
        "api_mode_override": binding.api_mode_override.value if binding.api_mode_override is not None else None,
        "prompt_profile": binding.prompt_profile,
        "enabled": binding.enabled,
        "updated_at": binding.updated_at,
    }


def serialize_llm_provider(provider: LlmProvider) -> dict:
    return {
        "provider_id": provider.provider_id,
        "name": provider.name,
        "vendor": provider.vendor,
        "base_url": provider.base_url,
        "api_mode": provider.api_mode.value,
        "model": provider.model,
        "api_key_ref": provider.api_key_ref,
        "timeout_seconds": float(provider.timeout_seconds),
        "max_retries": int(provider.max_retries),
        "max_input_chars": int(provider.max_input_chars),
        "enabled": provider.enabled,
        "is_default": provider.is_default,
        "extra_config": provider.extra_json or {},
        "created_at": provider.created_at,
        "updated_at": provider.updated_at,
    }


def _clear_default_provider(db: Session) -> None:
    defaults = db.scalars(select(LlmProvider).where(LlmProvider.is_default.is_(True))).all()
    for row in defaults:
        row.is_default = False


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
