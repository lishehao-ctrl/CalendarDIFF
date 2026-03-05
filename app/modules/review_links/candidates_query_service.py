from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import EventLinkBlock, EventLinkCandidate, EventLinkCandidateStatus
from app.modules.review_links.common import load_entity_preview, load_observation_snapshot


def list_link_candidates(
    db: Session,
    *,
    user_id: int,
    status: str,
    source_id: int | None,
    limit: int,
    offset: int,
) -> list[dict]:
    stmt = (
        select(EventLinkCandidate)
        .where(EventLinkCandidate.user_id == user_id)
        .order_by(EventLinkCandidate.created_at.desc(), EventLinkCandidate.id.desc())
        .offset(offset)
        .limit(limit)
    )
    if status == "pending":
        stmt = stmt.where(EventLinkCandidate.status == EventLinkCandidateStatus.PENDING)
    elif status == "approved":
        stmt = stmt.where(EventLinkCandidate.status == EventLinkCandidateStatus.APPROVED)
    elif status == "rejected":
        stmt = stmt.where(EventLinkCandidate.status == EventLinkCandidateStatus.REJECTED)

    if source_id is not None:
        stmt = stmt.where(EventLinkCandidate.source_id == source_id)

    rows = db.scalars(stmt).all()
    out: list[dict] = []
    for row in rows:
        proposed_entity = load_entity_preview(db=db, user_id=user_id, entity_uid=row.proposed_entity_uid)
        evidence = load_observation_snapshot(
            db=db,
            user_id=user_id,
            source_id=row.source_id,
            external_event_id=row.external_event_id,
        )
        out.append(
            {
                "id": row.id,
                "source_id": row.source_id,
                "external_event_id": row.external_event_id,
                "proposed_entity_uid": row.proposed_entity_uid,
                "score": float(row.score) if isinstance(row.score, (int, float)) else None,
                "score_breakdown": row.score_breakdown_json if isinstance(row.score_breakdown_json, dict) else {},
                "reason_code": row.reason_code.value,
                "status": row.status.value,
                "reviewed_by_user_id": row.reviewed_by_user_id,
                "reviewed_at": row.reviewed_at,
                "review_note": row.review_note,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "evidence_snapshot": evidence,
                "proposed_entity": proposed_entity,
            }
        )
    return out


def list_link_blocks(
    db: Session,
    *,
    user_id: int,
    source_id: int | None,
    limit: int,
    offset: int,
) -> list[EventLinkBlock]:
    stmt = (
        select(EventLinkBlock)
        .where(EventLinkBlock.user_id == user_id)
        .order_by(EventLinkBlock.created_at.desc(), EventLinkBlock.id.desc())
        .offset(offset)
        .limit(limit)
    )
    if source_id is not None:
        stmt = stmt.where(EventLinkBlock.source_id == source_id)
    return db.scalars(stmt).all()
