from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.runtime import IngestJob, IngestJobStatus
from app.db.models.input import IngestTriggerType, InputSource, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.shared import User
from app.modules.runtime.connectors.job_claiming import claim_jobs


def _seed_source(db: Session, *, user_id: int, source_key: str) -> InputSource:
    source = InputSource(
        user_id=user_id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key=source_key,
        display_name=source_key,
        is_active=True,
        poll_interval_seconds=900,
    )
    db.add(source)
    db.flush()
    return source


def _seed_request_and_job(
    db: Session,
    *,
    source_id: int,
    request_id: str,
    idempotency_key: str,
    job_status: IngestJobStatus = IngestJobStatus.PENDING,
) -> None:
    now = datetime.now(timezone.utc)
    db.add(
        SyncRequest(
            request_id=request_id,
            source_id=source_id,
            trigger_type=IngestTriggerType.MANUAL,
            status=SyncRequestStatus.QUEUED,
            idempotency_key=idempotency_key,
            metadata_json={},
        )
    )
    db.add(
        IngestJob(
            request_id=request_id,
            source_id=source_id,
            status=job_status,
            attempt=0,
            next_retry_at=now - timedelta(seconds=1),
            payload_json={},
        )
    )


def test_claim_jobs_enforces_same_source_fifo(db_session: Session) -> None:
    user = User(email="fifo@example.com")
    db_session.add(user)
    db_session.flush()

    source_a = _seed_source(db_session, user_id=user.id, source_key="fifo-a")
    source_b = _seed_source(db_session, user_id=user.id, source_key="fifo-b")

    _seed_request_and_job(
        db_session,
        source_id=source_a.id,
        request_id="req-a-1",
        idempotency_key="req-a-1",
    )
    _seed_request_and_job(
        db_session,
        source_id=source_a.id,
        request_id="req-a-2",
        idempotency_key="req-a-2",
    )
    _seed_request_and_job(
        db_session,
        source_id=source_b.id,
        request_id="req-b-1",
        idempotency_key="req-b-1",
    )
    db_session.commit()

    claimed = claim_jobs(db_session, worker_id="test-worker")
    claimed_request_ids = {row.request_id for row in claimed}

    assert claimed_request_ids == {"req-a-1", "req-b-1"}

    jobs = db_session.scalars(select(IngestJob).order_by(IngestJob.id.asc())).all()
    assert jobs[0].status == IngestJobStatus.CLAIMED
    assert jobs[1].status == IngestJobStatus.PENDING
    assert jobs[2].status == IngestJobStatus.CLAIMED

    requests = db_session.scalars(select(SyncRequest).order_by(SyncRequest.id.asc())).all()
    assert requests[0].status == SyncRequestStatus.RUNNING
    assert requests[1].status == SyncRequestStatus.QUEUED
    assert requests[2].status == SyncRequestStatus.RUNNING


def test_claim_jobs_respects_existing_claimed_head(db_session: Session) -> None:
    user = User(email="fifo2@example.com")
    db_session.add(user)
    db_session.flush()

    source_a = _seed_source(db_session, user_id=user.id, source_key="fifo-head-a")
    source_b = _seed_source(db_session, user_id=user.id, source_key="fifo-head-b")

    _seed_request_and_job(
        db_session,
        source_id=source_a.id,
        request_id="req-a-head",
        idempotency_key="req-a-head",
        job_status=IngestJobStatus.CLAIMED,
    )
    _seed_request_and_job(
        db_session,
        source_id=source_a.id,
        request_id="req-a-tail",
        idempotency_key="req-a-tail",
    )
    _seed_request_and_job(
        db_session,
        source_id=source_b.id,
        request_id="req-b-tail",
        idempotency_key="req-b-tail",
    )
    db_session.commit()

    claimed = claim_jobs(db_session, worker_id="test-worker")
    claimed_request_ids = {row.request_id for row in claimed}
    assert claimed_request_ids == {"req-b-tail"}


def test_claim_jobs_does_not_block_newer_source_job_on_sleeping_retry_head(db_session: Session) -> None:
    user = User(email="fifo3@example.com")
    db_session.add(user)
    db_session.flush()

    source = _seed_source(db_session, user_id=user.id, source_key="fifo-sleeping-head")
    now = datetime.now(timezone.utc)

    db_session.add(
        SyncRequest(
            request_id="req-old-sleeping",
            source_id=source.id,
            trigger_type=IngestTriggerType.MANUAL,
            status=SyncRequestStatus.QUEUED,
            idempotency_key="req-old-sleeping",
            metadata_json={},
        )
    )
    db_session.add(
        IngestJob(
            request_id="req-old-sleeping",
            source_id=source.id,
            status=IngestJobStatus.PENDING,
            attempt=1,
            next_retry_at=now + timedelta(minutes=10),
            payload_json={},
        )
    )
    db_session.add(
        SyncRequest(
            request_id="req-new-ready",
            source_id=source.id,
            trigger_type=IngestTriggerType.MANUAL,
            status=SyncRequestStatus.QUEUED,
            idempotency_key="req-new-ready",
            metadata_json={},
        )
    )
    db_session.add(
        IngestJob(
            request_id="req-new-ready",
            source_id=source.id,
            status=IngestJobStatus.PENDING,
            attempt=0,
            next_retry_at=now - timedelta(seconds=1),
            payload_json={},
        )
    )
    db_session.commit()

    claimed = claim_jobs(db_session, worker_id="test-worker")
    claimed_request_ids = {row.request_id for row in claimed}
    assert claimed_request_ids == {"req-new-ready"}
