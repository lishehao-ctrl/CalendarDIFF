from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session, aliased

from app.contracts.events import new_event
from app.core.config import get_settings
from app.db.models import (
    ConnectorResultStatus,
    IngestJob,
    IngestJobStatus,
    IngestResult,
    InputSource,
    IntegrationOutbox,
    OutboxStatus,
    SyncRequest,
    SyncRequestStatus,
)
from app.modules.ingestion.ics_delta import (
    ICS_COMPONENT_FINGERPRINT_HASH_VERSION,
    IcsDeltaParseError,
    build_ics_delta,
)
from app.modules.input_control_plane.service import decode_source_secrets
from app.modules.llm_runtime.queue import ensure_stream_group, get_redis_client, queue_group, queue_stream_key
from app.modules.llm_runtime.worker import enqueue_llm_task
from app.modules.sync.gmail_client import GmailAPIError, GmailClient, GmailHistoryExpiredError, GmailMessageMetadata
from app.modules.sync.ics_client import ICSClient

CONNECTOR_BATCH_SIZE = 50
MAX_SYNC_ERROR_LENGTH = 512
logger = logging.getLogger(__name__)


def run_connector_tick(db: Session, *, worker_id: str) -> int:
    _requeue_stale_claimed_jobs(db)
    jobs = _claim_jobs(db, worker_id=worker_id)
    processed = 0
    for job in jobs:
        _process_job(db, job_id=job.id, worker_id=worker_id)
        processed += 1
    return processed


def _requeue_stale_claimed_jobs(db: Session) -> int:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    timeout_seconds = max(30, int(settings.llm_claim_timeout_seconds))
    cutoff = now - timedelta(seconds=timeout_seconds)
    rows = db.scalars(
        select(IngestJob)
        .where(
            IngestJob.status == IngestJobStatus.CLAIMED,
            IngestJob.updated_at <= cutoff,
            or_(IngestJob.next_retry_at.is_(None), IngestJob.next_retry_at <= now),
        )
        .order_by(IngestJob.id.asc())
        .with_for_update(skip_locked=True)
        .limit(CONNECTOR_BATCH_SIZE)
    ).all()
    if not rows:
        return 0

    max_attempts = max(1, int(settings.llm_max_retry_attempts))
    for row in rows:
        sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == row.request_id))
        source = db.get(InputSource, row.source_id)
        attempt = row.attempt + 1
        error_code = "llm_claim_timeout_requeue"
        error_message = "claimed job timed out before completion"
        payload = _job_payload(row)
        payload["last_error_code"] = error_code
        payload["last_error_message"] = error_message

        if attempt < max_attempts:
            row.attempt = attempt
            row.status = IngestJobStatus.PENDING
            row.next_retry_at = now + timedelta(seconds=_compute_retry_delay_seconds(attempt))
            row.claimed_by = None
            row.claim_token = None
            payload["workflow_stage"] = "CLAIM_TIMEOUT_REQUEUED"
            row.payload_json = payload
            if sync_request is not None:
                sync_request.status = SyncRequestStatus.QUEUED
                sync_request.error_code = error_code
                sync_request.error_message = _truncate(error_message)
            if source is not None:
                source.last_error_code = error_code
                source.last_error_message = _truncate(error_message)
            continue

        row.attempt = attempt
        row.status = IngestJobStatus.DEAD_LETTER
        row.next_retry_at = None
        row.dead_lettered_at = now
        row.claimed_by = None
        row.claim_token = None
        payload["workflow_stage"] = "CLAIM_TIMEOUT_DEAD_LETTER"
        row.payload_json = payload
        if sync_request is not None:
            sync_request.status = SyncRequestStatus.FAILED
            sync_request.error_code = error_code
            sync_request.error_message = _truncate(error_message)
        if source is not None:
            source.last_error_code = error_code
            source.last_error_message = _truncate(error_message)
    db.commit()
    return len(rows)


def _claim_jobs(db: Session, *, worker_id: str) -> list[IngestJob]:
    now = datetime.now(timezone.utc)
    older = aliased(IngestJob)
    rows = db.scalars(
        select(IngestJob)
        .where(
            IngestJob.status == IngestJobStatus.PENDING,
            or_(IngestJob.next_retry_at.is_(None), IngestJob.next_retry_at <= now),
            ~exists(
                select(1).where(
                    older.source_id == IngestJob.source_id,
                    older.id < IngestJob.id,
                    older.status.in_([IngestJobStatus.PENDING, IngestJobStatus.CLAIMED]),
                )
            ),
        )
        .order_by(IngestJob.id.asc())
        .with_for_update(skip_locked=True)
        .limit(CONNECTOR_BATCH_SIZE)
    ).all()
    claimed: list[IngestJob] = []
    for row in rows:
        row.status = IngestJobStatus.CLAIMED
        row.claimed_by = worker_id
        row.claim_token = uuid4().hex
        row.updated_at = now
        sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == row.request_id))
        if sync_request is not None:
            sync_request.status = SyncRequestStatus.RUNNING
            sync_request.error_code = None
            sync_request.error_message = None
        claimed.append(row)
    db.commit()
    return claimed


def _process_job(db: Session, *, job_id: int, worker_id: str) -> None:
    del worker_id
    now = datetime.now(timezone.utc)
    job = db.get(IngestJob, job_id)
    if job is None or job.status != IngestJobStatus.CLAIMED:
        return

    sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == job.request_id))
    source = db.get(InputSource, job.source_id)
    if sync_request is None or source is None:
        job.status = IngestJobStatus.DEAD_LETTER
        job.dead_lettered_at = now
        job.next_retry_at = None
        if sync_request is not None:
            sync_request.status = SyncRequestStatus.FAILED
            sync_request.error_code = "connector_context_missing"
            sync_request.error_message = "missing sync request/source context"
        db.commit()
        return

    result_status = ConnectorResultStatus.NO_CHANGE
    cursor_patch: dict = {}
    parse_payload: dict | None = None
    error_code: str | None = None
    error_message: str | None = None

    try:
        if source.provider == "gmail":
            result_status, cursor_patch, parse_payload, error_code, error_message = _run_gmail_connector_fetch_only(
                source=source,
                request_id=sync_request.request_id,
            )
        elif source.provider in {"ics", "calendar"}:
            result_status, cursor_patch, parse_payload, error_code, error_message = _run_calendar_connector_fetch_only(
                source=source,
            )
        else:
            result_status = ConnectorResultStatus.FETCH_FAILED
            error_code = "provider_not_implemented"
            error_message = f"provider not implemented: {source.provider}"
    except Exception as exc:  # pragma: no cover - defensive worker guard
        result_status = ConnectorResultStatus.FETCH_FAILED
        error_code = "connector_exception"
        error_message = str(exc)

    is_failure = result_status in {
        ConnectorResultStatus.FETCH_FAILED,
        ConnectorResultStatus.PARSE_FAILED,
        ConnectorResultStatus.AUTH_FAILED,
        ConnectorResultStatus.RATE_LIMITED,
    }
    if is_failure:
        _retry_or_fail_job(
            db,
            job=job,
            sync_request=sync_request,
            source=source,
            result_status=result_status,
            error_code=error_code,
            error_message=error_message,
        )
        return

    if parse_payload is not None:
        _queue_llm_parse_task(
            db,
            job=job,
            sync_request=sync_request,
            source=source,
            result_status=result_status,
            cursor_patch=cursor_patch,
            parse_payload=parse_payload,
        )
        return

    _mark_success_without_llm(
        db,
        job=job,
        sync_request=sync_request,
        source=source,
        result_status=result_status,
        cursor_patch=cursor_patch,
    )


def _queue_llm_parse_task(
    db: Session,
    *,
    job: IngestJob,
    sync_request: SyncRequest,
    source: InputSource,
    result_status: ConnectorResultStatus,
    cursor_patch: dict,
    parse_payload: dict,
) -> None:
    try:
        redis_client = get_redis_client()
        stream_key = queue_stream_key()
        ensure_stream_group(redis_client, stream_key=stream_key, group_name=queue_group())
        enqueue_llm_task(
            redis_client=redis_client,
            request_id=sync_request.request_id,
            source_id=source.id,
            attempt=job.attempt,
            reason="initial",
        )
    except Exception as exc:
        _retry_or_fail_job(
            db,
            job=job,
            sync_request=sync_request,
            source=source,
            result_status=ConnectorResultStatus.PARSE_FAILED,
            error_code="llm_queue_unavailable",
            error_message=str(exc),
        )
        return

    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = _job_payload(job)
    payload["provider"] = source.provider
    payload["workflow_stage"] = "LLM_QUEUED"
    payload["llm_task_id"] = sync_request.request_id
    payload["llm_enqueued_at"] = now.isoformat()
    payload["llm_parse_payload"] = parse_payload
    payload["llm_cursor_patch"] = cursor_patch
    payload["connector_status"] = result_status.value
    job.payload_json = payload
    job.status = IngestJobStatus.CLAIMED
    job.next_retry_at = now + timedelta(seconds=max(30, int(settings.llm_claim_timeout_seconds)))
    sync_request.status = SyncRequestStatus.RUNNING
    sync_request.error_code = None
    sync_request.error_message = None
    db.commit()


def _mark_success_without_llm(
    db: Session,
    *,
    job: IngestJob,
    sync_request: SyncRequest,
    source: InputSource,
    result_status: ConnectorResultStatus,
    cursor_patch: dict,
) -> None:
    fetched_at = datetime.now(timezone.utc)
    existing_result = db.scalar(select(IngestResult).where(IngestResult.request_id == sync_request.request_id))
    if existing_result is None:
        db.add(
            IngestResult(
                request_id=sync_request.request_id,
                source_id=source.id,
                provider=source.provider,
                status=result_status,
                cursor_patch=cursor_patch,
                records=[],
                fetched_at=fetched_at,
                error_code=None,
                error_message=None,
            )
        )
        event = new_event(
            event_type="ingest.result.ready",
            aggregate_type="ingest_result",
            aggregate_id=sync_request.request_id,
            payload={
                "request_id": sync_request.request_id,
                "source_id": source.id,
                "provider": source.provider,
                "status": result_status.value,
            },
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

    if source.cursor is not None and cursor_patch:
        merged = dict(source.cursor.cursor_json or {})
        merged.update(cursor_patch)
        source.cursor.cursor_json = merged
        source.cursor.version += 1
    source.last_polled_at = fetched_at
    source.next_poll_at = fetched_at + timedelta(seconds=max(source.poll_interval_seconds, 30))
    source.last_error_code = None
    source.last_error_message = None
    job.status = IngestJobStatus.SUCCEEDED
    job.next_retry_at = None
    sync_request.status = SyncRequestStatus.SUCCEEDED
    sync_request.error_code = None
    sync_request.error_message = None
    db.commit()


def _retry_or_fail_job(
    db: Session,
    *,
    job: IngestJob,
    sync_request: SyncRequest,
    source: InputSource,
    result_status: ConnectorResultStatus,
    error_code: str | None,
    error_message: str | None,
) -> None:
    now = datetime.now(timezone.utc)
    settings = get_settings()
    normalized_code = (error_code or "connector_failed").strip() or "connector_failed"
    normalized_message = _truncate(error_message or normalized_code)
    retryable = _is_retryable_failure(result_status=result_status, error_code=normalized_code)
    max_attempts = max(1, int(settings.llm_max_retry_attempts))
    next_attempt = job.attempt + 1

    payload = _job_payload(job)
    payload["last_error_code"] = normalized_code
    payload["last_error_message"] = normalized_message

    if retryable and next_attempt < max_attempts:
        delay_seconds = _compute_retry_delay_seconds(next_attempt)
        job.attempt = next_attempt
        job.status = IngestJobStatus.PENDING
        job.next_retry_at = now + timedelta(seconds=delay_seconds)
        job.claimed_by = None
        job.claim_token = None
        payload["workflow_stage"] = "CONNECTOR_RETRY_WAITING"
        payload["next_retry_at"] = job.next_retry_at.isoformat() if job.next_retry_at else None
        job.payload_json = payload
        sync_request.status = SyncRequestStatus.QUEUED
        sync_request.error_code = normalized_code
        sync_request.error_message = normalized_message
        source.last_error_code = normalized_code
        source.last_error_message = normalized_message
        db.commit()
        return

    job.attempt = next_attempt
    job.status = IngestJobStatus.DEAD_LETTER
    job.dead_lettered_at = now
    job.next_retry_at = None
    job.claimed_by = None
    job.claim_token = None
    payload["workflow_stage"] = "CONNECTOR_DEAD_LETTER"
    payload["dead_lettered_at"] = now.isoformat()
    job.payload_json = payload
    sync_request.status = SyncRequestStatus.FAILED
    sync_request.error_code = normalized_code
    sync_request.error_message = normalized_message
    source.last_error_code = normalized_code
    source.last_error_message = normalized_message
    db.commit()


def _run_gmail_connector_fetch_only(
    *,
    source: InputSource,
    request_id: str,
) -> tuple[ConnectorResultStatus, dict, dict | None, str | None, str | None]:
    secrets = decode_source_secrets(source)
    access_token = secrets.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        return (
            ConnectorResultStatus.AUTH_FAILED,
            {},
            None,
            "gmail_missing_access_token",
            "missing access token for gmail source",
        )
    client = GmailClient()
    try:
        profile = client.get_profile(access_token=access_token)
    except GmailAPIError as exc:
        if exc.status_code in {401, 403}:
            return ConnectorResultStatus.AUTH_FAILED, {}, None, "gmail_auth_failed", str(exc)
        if exc.status_code == 429:
            return ConnectorResultStatus.RATE_LIMITED, {}, None, "gmail_rate_limited", str(exc)
        return ConnectorResultStatus.FETCH_FAILED, {}, None, "gmail_fetch_failed", str(exc)

    cursor = source.cursor.cursor_json if source.cursor is not None and isinstance(source.cursor.cursor_json, dict) else {}
    cursor_history_id = cursor.get("history_id") if isinstance(cursor.get("history_id"), str) else None

    if cursor_history_id is None:
        if profile.history_id:
            return ConnectorResultStatus.NO_CHANGE, {"history_id": profile.history_id}, None, None, None
        return ConnectorResultStatus.NO_CHANGE, {}, None, None, None

    try:
        history_result = client.list_history(
            access_token=access_token,
            start_history_id=cursor_history_id,
        )
    except GmailHistoryExpiredError:
        if profile.history_id:
            return ConnectorResultStatus.NO_CHANGE, {"history_id": profile.history_id}, None, None, None
        return ConnectorResultStatus.NO_CHANGE, {}, None, None, None
    except GmailAPIError as exc:
        if exc.status_code in {401, 403}:
            return ConnectorResultStatus.AUTH_FAILED, {}, None, "gmail_auth_failed", str(exc)
        if exc.status_code == 429:
            return ConnectorResultStatus.RATE_LIMITED, {}, None, "gmail_rate_limited", str(exc)
        return ConnectorResultStatus.FETCH_FAILED, {}, None, "gmail_fetch_failed", str(exc)

    latest_history_id = history_result.history_id or profile.history_id or cursor_history_id
    if not history_result.message_ids:
        return ConnectorResultStatus.NO_CHANGE, {"history_id": latest_history_id}, None, None, None

    config = source.config.config_json if source.config is not None and isinstance(source.config.config_json, dict) else {}
    message_payloads: list[dict] = []
    for message_id in history_result.message_ids:
        try:
            metadata = client.get_message_metadata(access_token=access_token, message_id=message_id)
        except GmailAPIError as exc:
            if exc.status_code in {401, 403}:
                return ConnectorResultStatus.AUTH_FAILED, {}, None, "gmail_auth_failed", str(exc)
            if exc.status_code == 429:
                return ConnectorResultStatus.RATE_LIMITED, {}, None, "gmail_rate_limited", str(exc)
            return ConnectorResultStatus.FETCH_FAILED, {}, None, "gmail_fetch_failed", str(exc)

        if not _matches_gmail_source_filters(metadata=metadata, config=config):
            continue

        message_payloads.append(
            {
                "message_id": metadata.message_id,
                "thread_id": metadata.thread_id,
                "subject": metadata.subject,
                "snippet": metadata.snippet,
                "body_text": metadata.body_text,
                "from_header": metadata.from_header,
                "internal_date": metadata.internal_date,
                "label_ids": metadata.label_ids,
                "history_id": latest_history_id,
                "account_email": profile.email_address,
                "request_id": request_id,
            }
        )

    cursor_patch = {"history_id": latest_history_id}
    if not message_payloads:
        return ConnectorResultStatus.NO_CHANGE, cursor_patch, None, None, None

    return (
        ConnectorResultStatus.CHANGED,
        cursor_patch,
        {"kind": "gmail", "messages": message_payloads},
        None,
        None,
    )


def _run_calendar_connector_fetch_only(
    *,
    source: InputSource,
) -> tuple[ConnectorResultStatus, dict, dict | None, str | None, str | None]:
    secrets = decode_source_secrets(source)
    url = secrets.get("url")
    if not isinstance(url, str) or not url:
        return (
            ConnectorResultStatus.AUTH_FAILED,
            {},
            None,
            "calendar_missing_url",
            "missing calendar url in source secrets",
        )

    cursor = source.cursor.cursor_json if source.cursor is not None and isinstance(source.cursor.cursor_json, dict) else {}
    if_none_match = cursor.get("etag") if isinstance(cursor.get("etag"), str) else None
    if_modified_since = cursor.get("last_modified") if isinstance(cursor.get("last_modified"), str) else None

    client = ICSClient()
    fetched = client.fetch(url, source.id, if_none_match=if_none_match, if_modified_since=if_modified_since)
    if fetched.not_modified:
        return (
            ConnectorResultStatus.NO_CHANGE,
            {
                "etag": fetched.etag,
                "last_modified": fetched.last_modified,
                "ics_delta_components_total": 0,
                "ics_delta_changed_components": 0,
                "ics_delta_removed_components": 0,
                "ics_delta_invalid_components": 0,
            },
            None,
            None,
            None,
        )
    if fetched.content is None:
        return ConnectorResultStatus.FETCH_FAILED, {}, None, "calendar_empty_content", "calendar fetch returned empty content"

    previous_fingerprints = _extract_ics_component_fingerprints(cursor)
    try:
        delta = build_ics_delta(content=fetched.content, previous_fingerprints=previous_fingerprints)
    except IcsDeltaParseError as exc:
        return ConnectorResultStatus.PARSE_FAILED, {}, None, "calendar_delta_parse_failed", str(exc)

    cursor_patch = {
        "etag": fetched.etag,
        "last_modified": fetched.last_modified,
        "ics_component_fingerprints_v1": delta.next_fingerprints,
        "ics_delta_components_total": delta.total_components,
        "ics_delta_changed_components": delta.changed_components_count,
        "ics_delta_removed_components": delta.removed_components_count,
        "ics_delta_invalid_components": delta.invalid_components,
    }
    if delta.changed_components_count + delta.removed_components_count == 0:
        return ConnectorResultStatus.NO_CHANGE, cursor_patch, None, None, None

    payload = {
        "kind": "calendar_delta_v1",
        "changed_components": delta.changed_components,
        "removed_component_keys": delta.removed_component_keys,
        "snapshot_meta": {
            "etag": fetched.etag,
            "last_modified": fetched.last_modified,
            "hash_version": ICS_COMPONENT_FINGERPRINT_HASH_VERSION,
        },
    }
    return ConnectorResultStatus.CHANGED, cursor_patch, payload, None, None


def _matches_gmail_source_filters(*, metadata: GmailMessageMetadata, config: dict) -> bool:
    label_id = config.get("label_id")
    if isinstance(label_id, str) and label_id.strip():
        if label_id not in metadata.label_ids:
            return False

    label_ids = config.get("label_ids")
    if isinstance(label_ids, list):
        normalized_label_ids = [value for value in label_ids if isinstance(value, str) and value.strip()]
        if normalized_label_ids and not any(label in metadata.label_ids for label in normalized_label_ids):
            return False

    from_contains = config.get("from_contains")
    if isinstance(from_contains, str) and from_contains.strip():
        if from_contains.strip().lower() not in metadata.from_header.lower():
            return False

    subject_keywords = config.get("subject_keywords")
    if isinstance(subject_keywords, list):
        normalized_keywords = [value.strip().lower() for value in subject_keywords if isinstance(value, str) and value.strip()]
        if normalized_keywords:
            subject_text = metadata.subject.lower()
            if not any(keyword in subject_text for keyword in normalized_keywords):
                return False

    return True


def _extract_ics_component_fingerprints(cursor: dict) -> dict[str, str]:
    raw = cursor.get("ics_component_fingerprints_v1")
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        normalized[key.strip()] = value.strip()
    return normalized


def _compute_retry_delay_seconds(attempt: int) -> int:
    settings = get_settings()
    exponent = max(attempt - 1, 0)
    base_seconds = max(1, int(settings.llm_retry_base_seconds))
    max_seconds = max(base_seconds, int(settings.llm_retry_max_seconds))
    jitter_seconds = max(0, int(settings.llm_retry_jitter_seconds))
    delay = min(base_seconds * (2**exponent), max_seconds)
    if jitter_seconds > 0:
        delay += random.randint(0, jitter_seconds)
    return max(1, int(delay))


def _is_retryable_failure(*, result_status: ConnectorResultStatus, error_code: str) -> bool:
    code = error_code.lower()
    if result_status == ConnectorResultStatus.AUTH_FAILED:
        return False
    if result_status == ConnectorResultStatus.RATE_LIMITED:
        return True
    if "rate_limit" in code:
        return True
    if "timeout" in code:
        return True
    if "upstream" in code:
        return True
    if "fetch_failed" in code:
        return True
    if "queue_unavailable" in code:
        return True
    if "connector_exception" in code:
        return True
    return result_status in {ConnectorResultStatus.FETCH_FAILED, ConnectorResultStatus.PARSE_FAILED}


def _job_payload(job: IngestJob) -> dict:
    if isinstance(job.payload_json, dict):
        return dict(job.payload_json)
    return {}


def _truncate(message: str, max_len: int = MAX_SYNC_ERROR_LENGTH) -> str:
    value = (message or "").strip()
    if len(value) <= max_len:
        return value
    return value[:max_len]
