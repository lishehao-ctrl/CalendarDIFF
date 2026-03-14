from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.ingestion import ConnectorResultStatus, IngestJob, IngestJobStatus
from app.modules.ingestion.calendar_fetcher import fetch_calendar_delta
from app.modules.ingestion.connector_apply import apply_failure, apply_success_without_llm, mark_llm_enqueue_pending
from app.modules.ingestion.connector_dispatch import dispatch_pending_llm_enqueues
from app.modules.ingestion.connector_types import ConnectorFetchOutcome
from app.modules.ingestion.failure_policy import decide_failure
from app.modules.ingestion.gmail_fetcher import fetch_gmail_changes
from app.modules.ingestion.job_claiming import claim_jobs, requeue_stale_claimed_jobs
from app.modules.runtime_kernel import JobContext, apply_dead_letter_transition, utcnow

logger = logging.getLogger(__name__)


def run_connector_tick(db: Session, *, worker_id: str) -> int:
    requeue_stale_claimed_jobs(db)
    dispatch_pending_llm_enqueues(db)
    jobs = claim_jobs(db, worker_id=worker_id)
    processed = 0
    for job in jobs:
        if process_claimed_job(db, job_id=job.id):
            processed += 1
    return processed


def process_claimed_job(db: Session, *, job_id: int) -> bool:
    settings = get_settings()
    now = utcnow()
    job = db.scalar(select(IngestJob).where(IngestJob.id == job_id).with_for_update())
    if job is None or job.status != IngestJobStatus.CLAIMED:
        return False

    sync_request = job.sync_request
    source = job.source
    context = JobContext(job=job, sync_request=sync_request, source=source)
    if sync_request is None or source is None:
        apply_dead_letter_transition(
            context=context,
            error_code="connector_context_missing",
            error_message="missing sync request/source context",
            attempt=job.attempt + 1,
            dead_lettered_at=now,
            workflow_stage="CONNECTOR_DEAD_LETTER",
            clear_claim=True,
            attempt_mode="set",
        )
        db.commit()
        return True

    outcome = dispatch_provider_fetch(source_provider=source.provider, source=source, request_id=sync_request.request_id)
    if outcome.status in {
        ConnectorResultStatus.FETCH_FAILED,
        ConnectorResultStatus.PARSE_FAILED,
        ConnectorResultStatus.AUTH_FAILED,
        ConnectorResultStatus.RATE_LIMITED,
    }:
        failure = decide_failure(
            result_status=outcome.status,
            error_code=outcome.error_code,
            error_message=outcome.error_message,
        )
        apply_failure(
            db,
            context=context,
            decision=failure,
            max_retry_attempts=int(settings.llm_max_retry_attempts),
            retry_base_seconds=int(settings.llm_retry_base_seconds),
            retry_max_seconds=int(settings.llm_retry_max_seconds),
            retry_jitter_seconds=int(settings.llm_retry_jitter_seconds),
        )
        db.commit()
        return True

    if outcome.parse_payload is not None:
        mark_llm_enqueue_pending(
            context=context,
            result_status=outcome.status,
            cursor_patch=outcome.cursor_patch,
            parse_payload=outcome.parse_payload,
            claim_timeout_seconds=int(settings.llm_claim_timeout_seconds),
        )
        db.commit()
        return True

    apply_success_without_llm(
        db,
        context=context,
        result_status=outcome.status,
        cursor_patch=outcome.cursor_patch,
    )
    db.commit()
    return True


def dispatch_provider_fetch(
    *,
    source_provider: str,
    source,
    request_id: str,
) -> ConnectorFetchOutcome:
    try:
        if source_provider == "gmail":
            return fetch_gmail_changes(source=source, request_id=request_id)
        if source_provider in {"ics", "calendar"}:
            return fetch_calendar_delta(source=source)
        return ConnectorFetchOutcome(
            status=ConnectorResultStatus.FETCH_FAILED,
            cursor_patch={},
            parse_payload=None,
            error_code="provider_not_implemented",
            error_message=f"provider not implemented: {source_provider}",
        )
    except Exception as exc:  # pragma: no cover - defensive worker guard
        logger.exception("connector fetch crashed provider=%s request_id=%s", source_provider, request_id)
        return ConnectorFetchOutcome(
            status=ConnectorResultStatus.FETCH_FAILED,
            cursor_patch={},
            parse_payload=None,
            error_code="connector_exception",
            error_message=str(exc),
        )


__all__ = ["dispatch_provider_fetch", "process_claimed_job", "run_connector_tick"]
