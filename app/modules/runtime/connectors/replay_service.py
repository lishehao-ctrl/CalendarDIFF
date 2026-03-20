from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.runtime import IngestJob, IngestJobStatus
from app.db.models.input import SyncRequest, SyncRequestStatus


class IngestJobNotFoundError(RuntimeError):
    pass


class IngestJobInvalidStateError(RuntimeError):
    pass


def replay_ingest_job(db: Session, *, job_id: int) -> IngestJob:
    now = datetime.now(timezone.utc)
    job = db.get(IngestJob, job_id)
    if job is None:
        raise IngestJobNotFoundError("ingest job not found")
    if job.status != IngestJobStatus.DEAD_LETTER:
        raise IngestJobInvalidStateError("ingest job is not dead-lettered")
    _restore_job_for_replay(db=db, job=job, now=now)
    db.commit()
    db.refresh(job)
    return job


def replay_dead_letter_jobs(db: Session, *, limit: int = 100) -> list[IngestJob]:
    now = datetime.now(timezone.utc)
    capped_limit = max(1, min(limit, 500))
    jobs = list(
        db.scalars(
            select(IngestJob)
            .where(IngestJob.status == IngestJobStatus.DEAD_LETTER)
            .order_by(IngestJob.dead_lettered_at.asc().nullslast(), IngestJob.id.asc())
            .limit(capped_limit)
        ).all()
    )
    if not jobs:
        return []
    for job in jobs:
        _restore_job_for_replay(db=db, job=job, now=now)
    db.commit()
    for job in jobs:
        db.refresh(job)
    return jobs


def _restore_job_for_replay(*, db: Session, job: IngestJob, now: datetime) -> None:
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


__all__ = [
    "IngestJobInvalidStateError",
    "IngestJobNotFoundError",
    "replay_dead_letter_jobs",
    "replay_ingest_job",
]
