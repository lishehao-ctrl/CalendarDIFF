from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import (
    Change,
    ChangeIntakePhase,
    ChangeOrigin,
    ChangeReviewBucket,
    ChangeType,
    ReviewStatus,
)
from app.modules.common.change_source_refs import (
    change_source_refs_as_dicts,
    normalize_source_refs,
    replace_change_source_refs,
    require_non_empty_source_refs,
)
from app.modules.common.payload_schemas import ChangeSourceRefPayload


def pending_change_same(
    row: Change,
    *,
    change_type: ChangeType,
    intake_phase: ChangeIntakePhase,
    review_bucket: ChangeReviewBucket,
    before_semantic_json: dict | None,
    after_semantic_json: dict | None,
    delta_seconds: int | None,
    source_refs: list[dict | ChangeSourceRefPayload],
) -> bool:
    normalized_refs = [item.model_dump(mode="json") for item in normalize_source_refs(source_refs)]
    return (
        row.change_type == change_type
        and row.intake_phase == intake_phase
        and row.review_bucket == review_bucket
        and row.before_semantic_json == before_semantic_json
        and row.after_semantic_json == after_semantic_json
        and row.delta_seconds == delta_seconds
        and change_source_refs_as_dicts(row) == normalized_refs
    )


def upsert_pending_change(
    *,
    db: Session,
    user_id: int,
    entity_uid: str,
    change_type: ChangeType,
    intake_phase: ChangeIntakePhase,
    review_bucket: ChangeReviewBucket,
    before_semantic_json: dict | None,
    after_semantic_json: dict | None,
    delta_seconds: int | None,
    source_refs: list[dict | ChangeSourceRefPayload],
    detected_at: datetime,
    before_evidence_json: dict | None = None,
    after_evidence_json: dict | None = None,
) -> Change | None:
    normalized_source_refs = require_non_empty_source_refs(
        source_refs=source_refs,
        context=f"pending_change user_id={user_id} entity_uid={entity_uid} change_type={change_type.value}",
    )
    existing_pending = db.scalar(
        select(Change)
        .where(
            Change.user_id == user_id,
            Change.entity_uid == entity_uid,
            Change.review_status == ReviewStatus.PENDING,
        )
        .order_by(Change.id.desc())
        .limit(1)
    )

    if existing_pending is None:
        change = Change(
            user_id=user_id,
            entity_uid=entity_uid,
            change_origin=ChangeOrigin.INGEST_PROPOSAL,
            change_type=change_type,
            intake_phase=intake_phase,
            review_bucket=review_bucket,
            detected_at=detected_at,
            before_semantic_json=before_semantic_json,
            after_semantic_json=after_semantic_json,
            delta_seconds=delta_seconds,
            before_evidence_json=before_evidence_json,
            after_evidence_json=after_evidence_json,
            viewed_at=None,
            viewed_note=None,
            review_status=ReviewStatus.PENDING,
            reviewed_at=None,
            review_note=None,
            reviewed_by_user_id=None,
        )
        db.add(change)
        replace_change_source_refs(change=change, source_refs=normalized_source_refs)
        db.flush()
        return change

    if pending_change_same(
        existing_pending,
        change_type=change_type,
        intake_phase=intake_phase,
        review_bucket=review_bucket,
        before_semantic_json=before_semantic_json,
        after_semantic_json=after_semantic_json,
        delta_seconds=delta_seconds,
        source_refs=normalized_source_refs,
    ):
        if existing_pending.before_evidence_json is None:
            existing_pending.before_evidence_json = before_evidence_json
        if existing_pending.after_evidence_json is None:
            existing_pending.after_evidence_json = after_evidence_json
        return None

    existing_pending.change_type = change_type
    existing_pending.intake_phase = intake_phase
    existing_pending.review_bucket = review_bucket
    existing_pending.detected_at = detected_at
    existing_pending.before_semantic_json = before_semantic_json
    existing_pending.after_semantic_json = after_semantic_json
    existing_pending.delta_seconds = delta_seconds
    replace_change_source_refs(change=existing_pending, source_refs=normalized_source_refs)
    existing_pending.before_evidence_json = before_evidence_json
    existing_pending.after_evidence_json = after_evidence_json
    existing_pending.viewed_at = None
    existing_pending.viewed_note = None
    existing_pending.review_status = ReviewStatus.PENDING
    existing_pending.reviewed_at = None
    existing_pending.review_note = None
    existing_pending.reviewed_by_user_id = None
    return None


def resolve_pending_change_as_rejected(
    *,
    db: Session,
    user_id: int,
    entity_uid: str,
    applied_at: datetime,
    note: str,
) -> None:
    pending = db.scalars(
        select(Change).where(
            Change.user_id == user_id,
            Change.entity_uid == entity_uid,
            Change.review_status == ReviewStatus.PENDING,
        )
    ).all()
    for row in pending:
        row.review_status = ReviewStatus.REJECTED
        row.reviewed_at = applied_at
        row.review_note = note
        row.reviewed_by_user_id = None


__all__ = [
    "pending_change_same",
    "resolve_pending_change_as_rejected",
    "upsert_pending_change",
]
