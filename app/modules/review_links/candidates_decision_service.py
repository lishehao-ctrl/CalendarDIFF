from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    EventEntityLink,
    EventLinkBlock,
    EventLinkCandidate,
    EventLinkCandidateStatus,
    EventLinkOrigin,
    InputSource,
    SourceKind,
)
from app.modules.review_links.common import dedupe_ids_preserve_order


class LinkCandidateNotFoundError(RuntimeError):
    pass


class LinkBlockNotFoundError(RuntimeError):
    pass


class LinkCandidateDecisionError(RuntimeError):
    pass


def batch_decide_link_candidates(
    db: Session,
    *,
    user_id: int,
    decision: str,
    ids: list[int],
    note: str | None,
) -> dict:
    deduped_ids = dedupe_ids_preserve_order(ids)
    results: list[dict] = []
    succeeded = 0
    for candidate_id in deduped_ids:
        try:
            row, idempotent, link_row, block_row = decide_link_candidate(
                db=db,
                user_id=user_id,
                candidate_id=candidate_id,
                decision=decision,
                note=note,
            )
            results.append(
                {
                    "id": candidate_id,
                    "ok": True,
                    "status": row.status.value,
                    "idempotent": idempotent,
                    "link_id": int(link_row.id) if link_row is not None else None,
                    "block_id": int(block_row.id) if block_row is not None else None,
                    "error_code": None,
                    "error_detail": None,
                }
            )
            succeeded += 1
        except LinkCandidateNotFoundError as exc:
            results.append(
                {
                    "id": candidate_id,
                    "ok": False,
                    "status": None,
                    "idempotent": False,
                    "link_id": None,
                    "block_id": None,
                    "error_code": "not_found",
                    "error_detail": str(exc),
                }
            )
        except LinkCandidateDecisionError as exc:
            results.append(
                {
                    "id": candidate_id,
                    "ok": False,
                    "status": None,
                    "idempotent": False,
                    "link_id": None,
                    "block_id": None,
                    "error_code": "invalid_state",
                    "error_detail": str(exc),
                }
            )
    failed = len(results) - succeeded
    return {
        "decision": decision,
        "total_requested": len(deduped_ids),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


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
    signals = (
        candidate.score_breakdown_json.get("incoming_signals")
        if isinstance(candidate.score_breakdown_json, dict)
        else None
    )
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
