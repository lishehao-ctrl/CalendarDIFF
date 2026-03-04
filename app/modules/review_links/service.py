from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Change,
    EventEntity,
    EventEntityLink,
    EventLinkAlert,
    EventLinkAlertResolution,
    EventLinkAlertStatus,
    EventLinkBlock,
    EventLinkCandidate,
    EventLinkCandidateStatus,
    EventLinkOrigin,
    Input,
    InputSource,
    ReviewStatus,
    SourceEventObservation,
    SourceKind,
)
from app.modules.review_links.alerts_service import resolve_pending_link_alerts_for_pair


class LinkCandidateNotFoundError(RuntimeError):
    pass


class LinkBlockNotFoundError(RuntimeError):
    pass


class LinkCandidateDecisionError(RuntimeError):
    pass


class LinkNotFoundError(RuntimeError):
    pass


class LinkAlertNotFoundError(RuntimeError):
    pass


def get_review_items_summary(
    db: Session,
    *,
    user_id: int,
) -> dict:
    changes_pending = int(
        db.scalar(
            select(func.count(Change.id))
            .join(Input, Input.id == Change.input_id)
            .where(
                Input.user_id == user_id,
                Change.review_status == ReviewStatus.PENDING,
            )
        )
        or 0
    )
    link_candidates_pending = int(
        db.scalar(
            select(func.count(EventLinkCandidate.id)).where(
                EventLinkCandidate.user_id == user_id,
                EventLinkCandidate.status == EventLinkCandidateStatus.PENDING,
            )
        )
        or 0
    )
    link_alerts_pending = int(
        db.scalar(
            select(func.count(EventLinkAlert.id)).where(
                EventLinkAlert.user_id == user_id,
                EventLinkAlert.status == EventLinkAlertStatus.PENDING,
            )
        )
        or 0
    )
    return {
        "changes_pending": changes_pending,
        "link_candidates_pending": link_candidates_pending,
        "link_alerts_pending": link_alerts_pending,
        "generated_at": datetime.now(timezone.utc),
    }


def batch_decide_link_alerts(
    db: Session,
    *,
    user_id: int,
    decision: str,
    ids: list[int],
    note: str | None,
) -> dict:
    deduped_ids = _dedupe_ids_preserve_order(ids)
    results: list[dict] = []
    succeeded = 0
    for alert_id in deduped_ids:
        try:
            if decision == "dismiss":
                row, idempotent = dismiss_link_alert(
                    db=db,
                    user_id=user_id,
                    alert_id=alert_id,
                    note=note,
                )
            else:
                row, idempotent = mark_safe_link_alert(
                    db=db,
                    user_id=user_id,
                    alert_id=alert_id,
                    note=note,
                )
            results.append(
                {
                    "id": alert_id,
                    "ok": True,
                    "status": row.status.value,
                    "idempotent": idempotent,
                    "reviewed_at": row.reviewed_at,
                    "review_note": row.review_note,
                    "error_code": None,
                    "error_detail": None,
                }
            )
            succeeded += 1
        except LinkAlertNotFoundError as exc:
            results.append(
                {
                    "id": alert_id,
                    "ok": False,
                    "status": None,
                    "idempotent": False,
                    "reviewed_at": None,
                    "review_note": None,
                    "error_code": "not_found",
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


def batch_decide_link_candidates(
    db: Session,
    *,
    user_id: int,
    decision: str,
    ids: list[int],
    note: str | None,
) -> dict:
    deduped_ids = _dedupe_ids_preserve_order(ids)
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


def list_link_alerts(
    db: Session,
    *,
    user_id: int,
    status: str,
    source_id: int | None,
    limit: int,
    offset: int,
) -> list[dict]:
    stmt = (
        select(EventLinkAlert)
        .where(EventLinkAlert.user_id == user_id)
        .order_by(EventLinkAlert.created_at.desc(), EventLinkAlert.id.desc())
        .offset(offset)
        .limit(limit)
    )
    if status == "pending":
        stmt = stmt.where(EventLinkAlert.status == EventLinkAlertStatus.PENDING)
    elif status == "dismissed":
        stmt = stmt.where(EventLinkAlert.status == EventLinkAlertStatus.DISMISSED)
    elif status == "marked_safe":
        stmt = stmt.where(EventLinkAlert.status == EventLinkAlertStatus.MARKED_SAFE)
    elif status == "resolved":
        stmt = stmt.where(EventLinkAlert.status == EventLinkAlertStatus.RESOLVED)
    if source_id is not None:
        stmt = stmt.where(EventLinkAlert.source_id == source_id)

    rows = db.scalars(stmt).all()
    out: list[dict] = []
    for row in rows:
        out.append(
            {
                "id": row.id,
                "source_id": row.source_id,
                "external_event_id": row.external_event_id,
                "entity_uid": row.entity_uid,
                "link_id": row.link_id,
                "status": row.status.value,
                "reason_code": row.reason_code.value,
                "resolution_code": row.resolution_code.value if row.resolution_code is not None else None,
                "risk_level": row.risk_level.value,
                "evidence_snapshot": row.evidence_snapshot_json if isinstance(row.evidence_snapshot_json, dict) else {},
                "reviewed_by_user_id": row.reviewed_by_user_id,
                "reviewed_at": row.reviewed_at,
                "review_note": row.review_note,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "linked_entity": _load_entity_preview(db=db, user_id=user_id, entity_uid=row.entity_uid),
            }
        )
    return out


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
                "linked_entity": _load_entity_preview(db=db, user_id=user_id, entity_uid=row.entity_uid),
            }
        )
    return out


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


def dismiss_link_alert(
    db: Session,
    *,
    user_id: int,
    alert_id: int,
    note: str | None,
) -> tuple[EventLinkAlert, bool]:
    row = db.scalar(
        select(EventLinkAlert)
        .where(
            EventLinkAlert.id == alert_id,
            EventLinkAlert.user_id == user_id,
        )
        .with_for_update()
    )
    if row is None:
        raise LinkAlertNotFoundError("Link alert not found")
    if row.status == EventLinkAlertStatus.DISMISSED:
        return row, True
    if row.status != EventLinkAlertStatus.PENDING:
        return row, True

    normalized_note = note.strip()[:512] if isinstance(note, str) and note.strip() else None
    now = datetime.now(timezone.utc)
    row.status = EventLinkAlertStatus.DISMISSED
    row.resolution_code = EventLinkAlertResolution.DISMISSED_BY_USER
    row.reviewed_by_user_id = user_id
    row.reviewed_at = now
    row.review_note = normalized_note
    db.commit()
    db.refresh(row)
    return row, False


def mark_safe_link_alert(
    db: Session,
    *,
    user_id: int,
    alert_id: int,
    note: str | None,
) -> tuple[EventLinkAlert, bool]:
    row = db.scalar(
        select(EventLinkAlert)
        .where(
            EventLinkAlert.id == alert_id,
            EventLinkAlert.user_id == user_id,
        )
        .with_for_update()
    )
    if row is None:
        raise LinkAlertNotFoundError("Link alert not found")
    if row.status == EventLinkAlertStatus.MARKED_SAFE:
        return row, True
    if row.status != EventLinkAlertStatus.PENDING:
        return row, True

    normalized_note = note.strip()[:512] if isinstance(note, str) and note.strip() else None
    now = datetime.now(timezone.utc)
    row.status = EventLinkAlertStatus.MARKED_SAFE
    row.resolution_code = EventLinkAlertResolution.MARKED_SAFE_BY_USER
    row.reviewed_by_user_id = user_id
    row.reviewed_at = now
    row.review_note = normalized_note
    db.commit()
    db.refresh(row)
    return row, False


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


def _dedupe_ids_preserve_order(ids: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for raw in ids:
        normalized = int(raw)
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out
