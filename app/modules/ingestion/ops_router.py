from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import require_internal_service_token
from app.db.session import get_db
from app.modules.ingestion.replay_service import (
    IngestJobInvalidStateError,
    IngestJobNotFoundError,
    replay_dead_letter_jobs,
    replay_ingest_job,
)
from app.modules.input_control_plane.schemas import DeadLetterReplayResponse, IngestJobReplayResponse

router = APIRouter(
    prefix="/internal/ingest",
    tags=["internal-ingest-ops"],
    dependencies=[Depends(require_internal_service_token({"ops", "ingest"}))],
)


@router.post("/jobs/{job_id}/replays", response_model=IngestJobReplayResponse)
def replay_single_ingest_job(
    job_id: int,
    db: Session = Depends(get_db),
) -> IngestJobReplayResponse:
    try:
        job = replay_ingest_job(db, job_id=job_id)
    except IngestJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IngestJobInvalidStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return IngestJobReplayResponse(
        job_id=job.id,
        request_id=job.request_id,
        status=job.status.value,
        next_retry_at=job.next_retry_at,
    )


@router.post("/jobs/dead-letter/replays", response_model=DeadLetterReplayResponse)
def replay_dead_letter(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> DeadLetterReplayResponse:
    replayed = replay_dead_letter_jobs(db, limit=limit)
    return DeadLetterReplayResponse(
        replayed_jobs=[
            IngestJobReplayResponse(
                job_id=job.id,
                request_id=job.request_id,
                status=job.status.value,
                next_retry_at=job.next_retry_at,
            )
            for job in replayed
        ]
    )
