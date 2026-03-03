from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    EventEntity,
    EventEntityLink,
    EventLinkBlock,
    EventLinkCandidate,
    EventLinkCandidateStatus,
    EventLinkOrigin,
    InputSource,
    SourceEventObservation,
    SourceKind,
)


class LinkCandidateNotFoundError(RuntimeError):
    pass


class LinkBlockNotFoundError(RuntimeError):
    pass


class LinkCandidateDecisionError(RuntimeError):
    pass


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
        proposed_entity = _load_entity_preview(db=db, user_id=user_id, entity_uid=row.proposed_entity_uid)
        evidence = _load_observation_snapshot(
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


def decide_link_candidate(
    db: Session,
    *,
    user_id: int,
    candidate_id: int,
    decision: str,
    note: str | None,
) -> tuple[EventLinkCandidate, bool, EventEntityLink | None, EventLinkBlock | None]:
    row = db.scalar(
        select(EventLinkCandidate)
        .where(
            EventLinkCandidate.id == candidate_id,
            EventLinkCandidate.user_id == user_id,
        )
        .with_for_update()
    )
    if row is None:
        raise LinkCandidateNotFoundError("Link candidate not found")

    if row.status != EventLinkCandidateStatus.PENDING:
        existing_link = _find_existing_link_for_candidate(db=db, candidate=row)
        existing_block = _find_existing_block_for_candidate(db=db, candidate=row)
        return row, True, existing_link, existing_block

    now = datetime.now(timezone.utc)
    link_row: EventEntityLink | None = None
    block_row: EventLinkBlock | None = None

    if decision == "approve":
        if not isinstance(row.proposed_entity_uid, str) or not row.proposed_entity_uid.strip():
            raise LinkCandidateDecisionError("Candidate has no proposed entity to approve")
        link_row = _upsert_manual_link(db=db, candidate=row)
        row.status = EventLinkCandidateStatus.APPROVED
    else:
        row.status = EventLinkCandidateStatus.REJECTED
        if isinstance(row.proposed_entity_uid, str) and row.proposed_entity_uid.strip():
            block_row = _upsert_link_block(
                db=db,
                user_id=user_id,
                source_id=row.source_id,
                external_event_id=row.external_event_id,
                blocked_entity_uid=row.proposed_entity_uid,
                created_by_user_id=user_id,
                note=note,
            )

    row.reviewed_by_user_id = user_id
    row.reviewed_at = now
    row.review_note = note

    db.commit()
    db.refresh(row)
    if link_row is not None:
        db.refresh(link_row)
    if block_row is not None:
        db.refresh(block_row)
    return row, False, link_row, block_row


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


def delete_link_block(
    db: Session,
    *,
    user_id: int,
    block_id: int,
) -> EventLinkBlock:
    row = db.scalar(
        select(EventLinkBlock)
        .where(
            EventLinkBlock.id == block_id,
            EventLinkBlock.user_id == user_id,
        )
        .with_for_update()
    )
    if row is None:
        raise LinkBlockNotFoundError("Link block not found")

    db.delete(row)
    db.commit()
    return row


def _load_entity_preview(*, db: Session, user_id: int, entity_uid: str | None) -> dict | None:
    if not isinstance(entity_uid, str) or not entity_uid.strip():
        return None
    row = db.scalar(
        select(EventEntity).where(
            EventEntity.user_id == user_id,
            EventEntity.entity_uid == entity_uid,
        )
    )
    if row is None:
        return {"entity_uid": entity_uid, "course_best_display": None, "course_best_strength": None}

    course_best = row.course_best_json if isinstance(row.course_best_json, dict) else {}
    display_name = course_best.get("display_name") if isinstance(course_best.get("display_name"), str) else None
    return {
        "entity_uid": row.entity_uid,
        "course_best_display": display_name,
        "course_best_strength": int(row.course_best_strength or 0),
    }


def _load_observation_snapshot(
    *,
    db: Session,
    user_id: int,
    source_id: int,
    external_event_id: str,
) -> dict | None:
    row = db.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.user_id == user_id,
            SourceEventObservation.source_id == source_id,
            SourceEventObservation.external_event_id == external_event_id,
        )
    )
    if row is None:
        return None

    payload = row.event_payload if isinstance(row.event_payload, dict) else {}
    source_canonical = payload.get("source_canonical") if isinstance(payload.get("source_canonical"), dict) else {}
    return {
        "merge_key": row.merge_key,
        "source_kind": row.source_kind.value,
        "source_title": source_canonical.get("source_title"),
        "source_dtstart_utc": source_canonical.get("source_dtstart_utc"),
        "source_dtend_utc": source_canonical.get("source_dtend_utc"),
        "is_active": row.is_active,
    }


def _find_existing_link_for_candidate(*, db: Session, candidate: EventLinkCandidate) -> EventEntityLink | None:
    return db.scalar(
        select(EventEntityLink).where(
            EventEntityLink.user_id == candidate.user_id,
            EventEntityLink.source_id == candidate.source_id,
            EventEntityLink.external_event_id == candidate.external_event_id,
        )
    )


def _find_existing_block_for_candidate(*, db: Session, candidate: EventLinkCandidate) -> EventLinkBlock | None:
    if not isinstance(candidate.proposed_entity_uid, str) or not candidate.proposed_entity_uid.strip():
        return None
    return db.scalar(
        select(EventLinkBlock).where(
            EventLinkBlock.user_id == candidate.user_id,
            EventLinkBlock.source_id == candidate.source_id,
            EventLinkBlock.external_event_id == candidate.external_event_id,
            EventLinkBlock.blocked_entity_uid == candidate.proposed_entity_uid,
        )
    )


def _upsert_manual_link(*, db: Session, candidate: EventLinkCandidate) -> EventEntityLink:
    source = db.get(InputSource, candidate.source_id)
    source_kind = source.source_kind if source is not None else SourceKind.EMAIL

    row = _find_existing_link_for_candidate(db=db, candidate=candidate)
    signals = candidate.score_breakdown_json.get("incoming_signals") if isinstance(candidate.score_breakdown_json, dict) else None
    if row is None:
        row = EventEntityLink(
            user_id=candidate.user_id,
            entity_uid=str(candidate.proposed_entity_uid),
            source_id=candidate.source_id,
            source_kind=source_kind,
            external_event_id=candidate.external_event_id,
            link_origin=EventLinkOrigin.MANUAL_CANDIDATE,
            link_score=float(candidate.score) if isinstance(candidate.score, (int, float)) else 0.0,
            signals_json=signals if isinstance(signals, dict) else None,
        )
        db.add(row)
        return row

    row.entity_uid = str(candidate.proposed_entity_uid)
    row.source_kind = source_kind
    row.link_origin = EventLinkOrigin.MANUAL_CANDIDATE
    row.link_score = float(candidate.score) if isinstance(candidate.score, (int, float)) else 0.0
    row.signals_json = signals if isinstance(signals, dict) else None
    return row


def _upsert_link_block(
    *,
    db: Session,
    user_id: int,
    source_id: int,
    external_event_id: str,
    blocked_entity_uid: str,
    created_by_user_id: int,
    note: str | None,
) -> EventLinkBlock:
    row = db.scalar(
        select(EventLinkBlock).where(
            EventLinkBlock.user_id == user_id,
            EventLinkBlock.source_id == source_id,
            EventLinkBlock.external_event_id == external_event_id,
            EventLinkBlock.blocked_entity_uid == blocked_entity_uid,
        )
    )
    if row is not None:
        if note is not None:
            row.note = note
        return row

    row = EventLinkBlock(
        user_id=user_id,
        source_id=source_id,
        external_event_id=external_event_id,
        blocked_entity_uid=blocked_entity_uid,
        created_by_user_id=created_by_user_id,
        note=note,
    )
    db.add(row)
    return row
