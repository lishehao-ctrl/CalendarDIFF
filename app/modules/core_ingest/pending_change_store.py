from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import Change, ChangeType, ReviewStatus


def pending_change_same(
    row: Change,
    *,
    change_type: ChangeType,
    before_json: dict | None,
    after_json: dict | None,
    delta_seconds: int | None,
    proposal_merge_key: str,
    proposal_sources_json: list[dict],
) -> bool:
    return (
        row.change_type == change_type
        and row.before_json == before_json
        and row.after_json == after_json
        and row.delta_seconds == delta_seconds
        and row.proposal_merge_key == proposal_merge_key
        and row.proposal_sources_json == proposal_sources_json
    )


def upsert_pending_change(
    *,
    db: Session,
    input_id: int,
    event_uid: str,
    change_type: ChangeType,
    before_json: dict | None,
    after_json: dict | None,
    delta_seconds: int | None,
    proposal_merge_key: str,
    proposal_sources_json: list[dict],
    detected_at: datetime,
) -> Change | None:
    existing_pending = db.scalar(
        select(Change)
        .where(
            Change.input_id == input_id,
            Change.event_uid == event_uid,
            Change.review_status == ReviewStatus.PENDING,
        )
        .order_by(Change.id.desc())
        .limit(1)
    )

    if existing_pending is None:
        change = Change(
            input_id=input_id,
            event_uid=event_uid,
            change_type=change_type,
            detected_at=detected_at,
            before_json=before_json,
            after_json=after_json,
            delta_seconds=delta_seconds,
            viewed_at=None,
            viewed_note=None,
            review_status=ReviewStatus.PENDING,
            reviewed_at=None,
            review_note=None,
            reviewed_by_user_id=None,
            proposal_merge_key=proposal_merge_key,
            proposal_sources_json=proposal_sources_json,
            before_snapshot_id=None,
            after_snapshot_id=None,
            evidence_keys=None,
        )
        db.add(change)
        db.flush()
        return change

    if pending_change_same(
        existing_pending,
        change_type=change_type,
        before_json=before_json,
        after_json=after_json,
        delta_seconds=delta_seconds,
        proposal_merge_key=proposal_merge_key,
        proposal_sources_json=proposal_sources_json,
    ):
        return None

    existing_pending.change_type = change_type
    existing_pending.detected_at = detected_at
    existing_pending.before_json = before_json
    existing_pending.after_json = after_json
    existing_pending.delta_seconds = delta_seconds
    existing_pending.viewed_at = None
    existing_pending.viewed_note = None
    existing_pending.review_status = ReviewStatus.PENDING
    existing_pending.reviewed_at = None
    existing_pending.review_note = None
    existing_pending.reviewed_by_user_id = None
    existing_pending.proposal_merge_key = proposal_merge_key
    existing_pending.proposal_sources_json = proposal_sources_json
    existing_pending.before_snapshot_id = None
    existing_pending.after_snapshot_id = None
    existing_pending.evidence_keys = None
    return None


def resolve_pending_change_as_rejected(
    *,
    db: Session,
    canonical_input_id: int,
    event_uid: str,
    applied_at: datetime,
    note: str,
) -> None:
    pending = db.scalars(
        select(Change).where(
            Change.input_id == canonical_input_id,
            Change.event_uid == event_uid,
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
