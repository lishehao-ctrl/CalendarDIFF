from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    IngestJob,
    IngestJobStatus,
    IngestTriggerType,
    InputSource,
    SourceKind,
    SyncRequest,
    SyncRequestStatus,
    User,
)
from app.modules.ingestion.connector_runtime import _requeue_stale_claimed_jobs


def _seed_claimed_job(
    db: Session,
    *,
    request_id: str,
    attempt: int,
) -> tuple[IngestJob, SyncRequest]:
    user = User(email=f"{request_id}@example.com", notify_email=f"{request_id}@example.com")
    db.add(user)
    db.flush()
    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key=f"src-{request_id}",
        display_name=f"src-{request_id}",
        is_active=True,
        poll_interval_seconds=900,
        last_error_code=None,
        last_error_message=None,
    )
    db.add(source)
    db.flush()
    sync_request = SyncRequest(
        request_id=request_id,
        source_id=source.id,
        trigger_type=IngestTriggerType.MANUAL,
        status=SyncRequestStatus.RUNNING,
        idempotency_key=request_id,
        metadata_json={},
    )
    db.add(sync_request)
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    job = IngestJob(
        request_id=request_id,
        source_id=source.id,
        status=IngestJobStatus.CLAIMED,
        attempt=attempt,
        next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        payload_json={"workflow_stage": "LLM_QUEUED"},
        updated_at=stale_time,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    db.refresh(sync_request)
    return job, sync_request


def test_requeue_stale_claimed_job(db_session: Session, monkeypatch) -> None:
    monkeypatch.setenv("LLM_CLAIM_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("LLM_MAX_RETRY_ATTEMPTS", "6")
    get_settings.cache_clear()
    try:
        job, sync_request = _seed_claimed_job(db_session, request_id="claim-requeue", attempt=0)
        recovered = _requeue_stale_claimed_jobs(db_session)
        assert recovered == 1

        db_session.refresh(job)
        db_session.refresh(sync_request)
        assert job.status == IngestJobStatus.PENDING
        assert job.attempt == 1
        assert job.next_retry_at is not None
        assert sync_request.status == SyncRequestStatus.QUEUED
        assert sync_request.error_code == "llm_claim_timeout_requeue"
    finally:
        get_settings.cache_clear()


def test_dead_letter_when_claim_timeout_exceeds_retries(db_session: Session, monkeypatch) -> None:
    monkeypatch.setenv("LLM_CLAIM_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("LLM_MAX_RETRY_ATTEMPTS", "2")
    get_settings.cache_clear()
    try:
        job, sync_request = _seed_claimed_job(db_session, request_id="claim-dead-letter", attempt=1)
        recovered = _requeue_stale_claimed_jobs(db_session)
        assert recovered == 1

        db_session.refresh(job)
        db_session.refresh(sync_request)
        assert job.status == IngestJobStatus.DEAD_LETTER
        assert job.dead_lettered_at is not None
        assert sync_request.status == SyncRequestStatus.FAILED
        assert sync_request.error_code == "llm_claim_timeout_requeue"
    finally:
        get_settings.cache_clear()
