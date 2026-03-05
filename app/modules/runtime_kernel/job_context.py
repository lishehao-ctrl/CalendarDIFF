from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.ingestion import IngestJob
from app.db.models.input import InputSource, SyncRequest


@dataclass(frozen=True)
class JobContext:
    job: IngestJob
    sync_request: SyncRequest | None
    source: InputSource | None


def load_job_context(
    db: Session,
    *,
    request_id: str,
    lock_job: bool = True,
) -> JobContext | None:
    stmt = select(IngestJob).where(IngestJob.request_id == request_id)
    if lock_job:
        stmt = stmt.with_for_update()
    job = db.scalar(stmt)
    if job is None:
        return None
    sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == request_id))
    source = db.get(InputSource, job.source_id)
    return JobContext(job=job, sync_request=sync_request, source=source)


__all__ = ["JobContext", "load_job_context"]
