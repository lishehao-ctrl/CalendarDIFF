from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import SyncRequest
from app.db.models.review import ChangeIntakePhase, ChangeReviewBucket, ChangeType, IngestApplyLog


@dataclass(frozen=True)
class ChangeIntakeClassification:
    intake_phase: ChangeIntakePhase
    review_bucket: ChangeReviewBucket


def classify_sync_request_intake_phase(
    db: Session,
    *,
    source_id: int,
    request_id: str,
) -> ChangeIntakePhase:
    current_row = db.scalar(
        select(SyncRequest)
        .where(
            SyncRequest.source_id == source_id,
            SyncRequest.request_id == request_id,
        )
        .limit(1)
    )
    if current_row is None:
        return ChangeIntakePhase.REPLAY

    earlier_applied_request_id = db.scalar(
        select(SyncRequest.request_id)
        .join(IngestApplyLog, IngestApplyLog.request_id == SyncRequest.request_id)
        .where(
            SyncRequest.source_id == source_id,
            (
                (SyncRequest.created_at < current_row.created_at)
                | (
                    (SyncRequest.created_at == current_row.created_at)
                    & (SyncRequest.id < current_row.id)
                )
            ),
        )
        .limit(1)
    )
    if isinstance(earlier_applied_request_id, str) and earlier_applied_request_id:
        return ChangeIntakePhase.REPLAY
    return ChangeIntakePhase.BASELINE


def derive_review_bucket(
    *,
    intake_phase: ChangeIntakePhase,
    change_type: ChangeType,
) -> ChangeReviewBucket:
    if intake_phase == ChangeIntakePhase.BASELINE and change_type == ChangeType.CREATED:
        return ChangeReviewBucket.INITIAL_REVIEW
    return ChangeReviewBucket.CHANGES


__all__ = [
    "ChangeIntakeClassification",
    "classify_sync_request_intake_phase",
    "derive_review_bucket",
]
