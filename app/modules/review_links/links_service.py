from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.models.review import EventEntityLink, EventLinkAlertResolution, EventLinkBlock, EventLinkCandidate, EventLinkCandidateStatus, EventLinkOrigin
from app.modules.review_links.alerts_upsert_service import resolve_pending_link_alerts_for_pair
from app.modules.review_links.candidates_decision_service import LinkCandidateDecisionError
from app.modules.review_links.common import load_entity_preview


class LinkNotFoundError(RuntimeError):
    pass


def list_links(
    db: Session,
    *,
    user_id: int,
    source_id: int | None,
    limit: int,
    offset: int,
) -> list[dict]:
    stmt = (
        select(EventEntityLink)
        .where(EventEntityLink.user_id == user_id)
        .order_by(EventEntityLink.updated_at.desc(), EventEntityLink.id.desc())
        .offset(offset)
        .limit(limit)
    )
    if source_id is not None:
        stmt = stmt.where(EventEntityLink.source_id == source_id)

    rows = db.scalars(stmt).all()
    out: list[dict] = []
    for row in rows:
        out.append(
            {
                "id": row.id,
                "source_id": row.source_id,
                "source_kind": row.source_kind.value,
                "external_event_id": row.external_event_id,
                "entity_uid": row.entity_uid,
                "link_origin": row.link_origin.value,
                "link_score": float(row.link_score) if isinstance(row.link_score, (int, float)) else None,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "signals": row.signals_json if isinstance(row.signals_json, dict) else None,
                "linked_entity": load_entity_preview(db=db, user_id=user_id, entity_uid=row.entity_uid),
            }
        )
    return out


def delete_link(
    db: Session,
    *,
    user_id: int,
    link_id: int,
    create_block: bool,
    note: str | None,
) -> tuple[int, EventLinkBlock | None]:
    row = db.scalar(
        select(EventEntityLink)
        .where(
            EventEntityLink.id == link_id,
            EventEntityLink.user_id == user_id,
        )
        .with_for_update()
    )
    if row is None:
        raise LinkNotFoundError("Link not found")

    deleted_id = int(row.id)
    block_row: EventLinkBlock | None = None
    if create_block:
        block_row = _upsert_link_block(
            db=db,
            user_id=user_id,
            source_id=row.source_id,
            external_event_id=row.external_event_id,
            blocked_entity_uid=row.entity_uid,
            created_by_user_id=user_id,
            note=note,
        )
    resolve_pending_link_alerts_for_pair(
        db=db,
        user_id=user_id,
        source_id=row.source_id,
        external_event_id=row.external_event_id,
        resolution_code=EventLinkAlertResolution.LINK_REMOVED,
        note="link_removed",
    )
    db.delete(row)
    db.commit()

    if block_row is not None:
        db.refresh(block_row)
    return deleted_id, block_row


def relink_observation(
    db: Session,
    *,
    user_id: int,
    source_id: int,
    external_event_id: str,
    entity_uid: str,
    clear_block: bool,
    note: str | None,
) -> tuple[EventEntityLink, int]:
    source = db.scalar(
        select(InputSource).where(
            InputSource.id == source_id,
            InputSource.user_id == user_id,
        )
    )
    if source is None:
        raise LinkCandidateDecisionError("Input source not found")

    cleared = 0
    if clear_block:
        blocked_rows = db.scalars(
            select(EventLinkBlock).where(
                EventLinkBlock.user_id == user_id,
                EventLinkBlock.source_id == source_id,
                EventLinkBlock.external_event_id == external_event_id,
                EventLinkBlock.blocked_entity_uid == entity_uid,
            )
        ).all()
        for blocked in blocked_rows:
            db.delete(blocked)
            cleared += 1

    link_row = db.scalar(
        select(EventEntityLink).where(
            EventEntityLink.user_id == user_id,
            EventEntityLink.source_id == source_id,
            EventEntityLink.external_event_id == external_event_id,
        )
    )
    signals_payload: dict | None = None
    if isinstance(note, str) and note.strip():
        signals_payload = {"manual_note": note.strip()[:512]}

    if link_row is None:
        link_row = EventEntityLink(
            user_id=user_id,
            source_id=source_id,
            source_kind=source.source_kind,
            external_event_id=external_event_id,
            entity_uid=entity_uid,
            link_origin=EventLinkOrigin.MANUAL_CANDIDATE,
            link_score=1.0,
            signals_json=signals_payload,
        )
        db.add(link_row)
    else:
        link_row.entity_uid = entity_uid
        link_row.source_kind = source.source_kind
        link_row.link_origin = EventLinkOrigin.MANUAL_CANDIDATE
        link_row.link_score = 1.0
        link_row.signals_json = signals_payload

    now = datetime.now(timezone.utc)
    pending_candidates = db.scalars(
        select(EventLinkCandidate).where(
            EventLinkCandidate.user_id == user_id,
            EventLinkCandidate.source_id == source_id,
            EventLinkCandidate.external_event_id == external_event_id,
            EventLinkCandidate.status == EventLinkCandidateStatus.PENDING,
        )
    ).all()
    for candidate in pending_candidates:
        candidate.status = EventLinkCandidateStatus.APPROVED
        candidate.reviewed_by_user_id = user_id
        candidate.reviewed_at = now
        candidate.review_note = "manual_relink"

    resolve_pending_link_alerts_for_pair(
        db=db,
        user_id=user_id,
        source_id=source_id,
        external_event_id=external_event_id,
        resolution_code=EventLinkAlertResolution.LINK_RELINKED,
        note="link_relinked",
    )
    db.commit()
    db.refresh(link_row)
    return link_row, cleared


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
