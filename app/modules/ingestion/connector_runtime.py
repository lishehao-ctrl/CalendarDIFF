from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.events import new_event
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
from app.modules.ingestion.llm_parsers import (
    LlmParseError,
    ParserContext,
    ParserOutput,
    parse_calendar_content,
    parse_gmail_payload,
)
from app.modules.input_control_plane.service import decode_source_secrets
from app.modules.sync.gmail_client import GmailAPIError, GmailClient, GmailHistoryExpiredError, GmailMessageMetadata
from app.modules.sync.ics_client import ICSClient

CONNECTOR_BATCH_SIZE = 50
MAX_RETRY_ATTEMPTS = 3
logger = logging.getLogger(__name__)


def run_connector_tick(db: Session, *, worker_id: str) -> int:
    jobs = _claim_jobs(db, worker_id=worker_id)
    processed = 0
    for job in jobs:
        _process_job(db, job_id=job.id, worker_id=worker_id)
        processed += 1
    return processed


def _claim_jobs(db: Session, *, worker_id: str) -> list[IngestJob]:
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(IngestJob)
        .where(
            IngestJob.status == IngestJobStatus.PENDING,
            IngestJob.next_retry_at <= now,
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
        claimed.append(row)
    db.commit()
    return claimed


def _process_job(db: Session, *, job_id: int, worker_id: str) -> None:
    del worker_id
    now = datetime.now(timezone.utc)
    job = db.get(IngestJob, job_id)
    if job is None:
        return
    sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == job.request_id))
    source = db.get(InputSource, job.source_id)
    if sync_request is None or source is None:
        job.status = IngestJobStatus.DEAD_LETTER
        job.dead_lettered_at = now
        db.commit()
        return

    result_status = ConnectorResultStatus.NO_CHANGE
    cursor_patch: dict = {}
    records: list[dict] = []
    error_code: str | None = None
    error_message: str | None = None
    fetched_at = now

    try:
        if source.provider == "gmail":
            result_status, cursor_patch, records, error_code, error_message = _run_gmail_connector(
                db=db,
                source=source,
                request_id=sync_request.request_id,
            )
        elif source.provider in {"ics", "calendar"}:
            result_status, cursor_patch, records, error_code, error_message = _run_calendar_connector(
                db=db,
                source=source,
                request_id=sync_request.request_id,
            )
        else:
            result_status = ConnectorResultStatus.FETCH_FAILED
            error_code = "provider_not_implemented"
            error_message = f"provider not implemented: {source.provider}"
    except Exception as exc:  # pragma: no cover - defensive worker guard
        result_status = ConnectorResultStatus.FETCH_FAILED
        error_code = "connector_exception"
        error_message = str(exc)

    if result_status == ConnectorResultStatus.PARSE_FAILED:
        logger.warning(
            "connector parse failed request_id=%s source_id=%s provider=%s code=%s",
            sync_request.request_id,
            source.id,
            source.provider,
            error_code,
        )

    fetched_at = datetime.now(timezone.utc)
    is_failure = result_status in {
        ConnectorResultStatus.FETCH_FAILED,
        ConnectorResultStatus.PARSE_FAILED,
        ConnectorResultStatus.AUTH_FAILED,
        ConnectorResultStatus.RATE_LIMITED,
    }

    if is_failure and job.attempt + 1 < MAX_RETRY_ATTEMPTS:
        job.attempt += 1
        job.status = IngestJobStatus.PENDING
        job.next_retry_at = now + timedelta(seconds=30 * (2**job.attempt))
        sync_request.status = SyncRequestStatus.QUEUED
        sync_request.error_code = error_code
        sync_request.error_message = error_message
        db.commit()
        return

    if is_failure:
        job.attempt += 1
        job.status = IngestJobStatus.DEAD_LETTER
        job.dead_lettered_at = now
        sync_request.status = SyncRequestStatus.FAILED
        sync_request.error_code = error_code
        sync_request.error_message = error_message
        source.last_error_code = error_code
        source.last_error_message = error_message
        db.commit()
        return

    existing_result = db.scalar(select(IngestResult).where(IngestResult.request_id == sync_request.request_id))
    if existing_result is None:
        db.add(
            IngestResult(
                request_id=sync_request.request_id,
                source_id=source.id,
                provider=source.provider,
                status=result_status,
                cursor_patch=cursor_patch,
                records=records,
                fetched_at=fetched_at,
                error_code=error_code,
                error_message=error_message,
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
    sync_request.status = SyncRequestStatus.SUCCEEDED
    sync_request.error_code = None
    sync_request.error_message = None
    db.commit()


def _run_gmail_connector(
    *,
    db: Session,
    source: InputSource,
    request_id: str,
) -> tuple[ConnectorResultStatus, dict, list[dict], str | None, str | None]:
    secrets = decode_source_secrets(source)
    access_token = secrets.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        return (
            ConnectorResultStatus.AUTH_FAILED,
            {},
            [],
            "gmail_missing_access_token",
            "missing access token for gmail source",
        )
    client = GmailClient()
    try:
        profile = client.get_profile(access_token=access_token)
    except GmailAPIError as exc:
        if exc.status_code in {401, 403}:
            return ConnectorResultStatus.AUTH_FAILED, {}, [], "gmail_auth_failed", str(exc)
        if exc.status_code == 429:
            return ConnectorResultStatus.RATE_LIMITED, {}, [], "gmail_rate_limited", str(exc)
        return ConnectorResultStatus.FETCH_FAILED, {}, [], "gmail_fetch_failed", str(exc)

    cursor = source.cursor.cursor_json if source.cursor is not None and isinstance(source.cursor.cursor_json, dict) else {}
    cursor_history_id = cursor.get("history_id") if isinstance(cursor.get("history_id"), str) else None

    # Baseline first run: record current history pointer and do not parse old mailbox backlog.
    if cursor_history_id is None:
        if profile.history_id:
            return ConnectorResultStatus.NO_CHANGE, {"history_id": profile.history_id}, [], None, None
        return ConnectorResultStatus.NO_CHANGE, {}, [], None, None

    try:
        history_result = client.list_history(
            access_token=access_token,
            start_history_id=cursor_history_id,
        )
    except GmailHistoryExpiredError:
        # History cursor is stale; reset baseline to latest known history id.
        if profile.history_id:
            return ConnectorResultStatus.NO_CHANGE, {"history_id": profile.history_id}, [], None, None
        return ConnectorResultStatus.NO_CHANGE, {}, [], None, None
    except GmailAPIError as exc:
        if exc.status_code in {401, 403}:
            return ConnectorResultStatus.AUTH_FAILED, {}, [], "gmail_auth_failed", str(exc)
        if exc.status_code == 429:
            return ConnectorResultStatus.RATE_LIMITED, {}, [], "gmail_rate_limited", str(exc)
        return ConnectorResultStatus.FETCH_FAILED, {}, [], "gmail_fetch_failed", str(exc)

    latest_history_id = history_result.history_id or profile.history_id or cursor_history_id
    if not history_result.message_ids:
        return ConnectorResultStatus.NO_CHANGE, {"history_id": latest_history_id}, [], None, None

    config = source.config.config_json if source.config is not None and isinstance(source.config.config_json, dict) else {}
    message_ids = history_result.message_ids
    records: list[dict] = []
    for message_id in message_ids:
        try:
            metadata = client.get_message_metadata(access_token=access_token, message_id=message_id)
        except GmailAPIError as exc:
            if exc.status_code in {401, 403}:
                return ConnectorResultStatus.AUTH_FAILED, {}, [], "gmail_auth_failed", str(exc)
            if exc.status_code == 429:
                return ConnectorResultStatus.RATE_LIMITED, {}, [], "gmail_rate_limited", str(exc)
            return ConnectorResultStatus.FETCH_FAILED, {}, [], "gmail_fetch_failed", str(exc)

        if not _matches_gmail_source_filters(metadata=metadata, config=config):
            continue

        context = ParserContext(
            source_id=source.id,
            provider=source.provider,
            source_kind=source.source_kind.value,
            request_id=request_id,
        )
        payload = {
            "message_id": metadata.message_id,
            "subject": metadata.subject,
            "snippet": metadata.snippet,
            "body_text": metadata.body_text,
            "from_header": metadata.from_header,
            "internal_date": metadata.internal_date,
            "label_ids": metadata.label_ids,
            "history_id": latest_history_id,
            "account_email": profile.email_address,
        }
        try:
            parser_output = parse_gmail_payload(db=db, payload=payload, context=context)
        except LlmParseError as exc:
            return ConnectorResultStatus.PARSE_FAILED, {}, [], exc.code, str(exc)
        records.extend(_attach_parser_metadata(records=parser_output.records, parser_output=parser_output))

    cursor_patch = {"history_id": latest_history_id}
    status = ConnectorResultStatus.CHANGED if records else ConnectorResultStatus.NO_CHANGE
    return status, cursor_patch, records, None, None


def _run_calendar_connector(
    *,
    db: Session,
    source: InputSource,
    request_id: str,
) -> tuple[ConnectorResultStatus, dict, list[dict], str | None, str | None]:
    secrets = decode_source_secrets(source)
    url = secrets.get("url")
    if not isinstance(url, str) or not url:
        return (
            ConnectorResultStatus.AUTH_FAILED,
            {},
            [],
            "calendar_missing_url",
            "missing calendar url in source secrets",
        )

    cursor = source.cursor.cursor_json if source.cursor is not None and isinstance(source.cursor.cursor_json, dict) else {}
    if_none_match = cursor.get("etag") if isinstance(cursor.get("etag"), str) else None
    if_modified_since = cursor.get("last_modified") if isinstance(cursor.get("last_modified"), str) else None

    client = ICSClient()
    fetched = client.fetch(url, source.id, if_none_match=if_none_match, if_modified_since=if_modified_since)
    if fetched.not_modified:
        return ConnectorResultStatus.NO_CHANGE, {"etag": fetched.etag, "last_modified": fetched.last_modified}, [], None, None
    if fetched.content is None:
        return ConnectorResultStatus.FETCH_FAILED, {}, [], "calendar_empty_content", "calendar fetch returned empty content"

    context = ParserContext(
        source_id=source.id,
        provider=source.provider,
        source_kind=source.source_kind.value,
        request_id=request_id,
    )
    try:
        parser_output = parse_calendar_content(db=db, content=fetched.content, context=context)
    except LlmParseError as exc:
        return ConnectorResultStatus.PARSE_FAILED, {}, [], exc.code, str(exc)

    records = _attach_parser_metadata(records=parser_output.records, parser_output=parser_output)
    cursor_patch = {
        "etag": fetched.etag,
        "last_modified": fetched.last_modified,
    }
    status = ConnectorResultStatus.CHANGED if records else ConnectorResultStatus.NO_CHANGE
    return status, cursor_patch, records, None, None


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


def _attach_parser_metadata(*, records: list[dict], parser_output: ParserOutput) -> list[dict]:
    parser_meta = {
        "name": parser_output.parser_name,
        "version": parser_output.parser_version,
        "model": parser_output.model_hint,
    }
    enriched: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        record_type = record.get("record_type")
        payload = record.get("payload")
        if not isinstance(record_type, str) or not isinstance(payload, dict):
            continue
        payload_json = dict(payload)
        payload_json["_parser"] = parser_meta
        enriched.append(
            {
                "record_type": record_type,
                "payload": payload_json,
            }
        )
    return enriched
