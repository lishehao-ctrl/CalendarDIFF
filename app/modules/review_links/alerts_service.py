from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import EventLinkAlert, EventLinkAlertReason, EventLinkAlertResolution, EventLinkAlertRiskLevel, EventLinkAlertStatus
from app.modules.review_links.common import (
    build_batch_result_error,
    build_batch_result_success,
    dedupe_ids_preserve_order,
    load_entity_preview,
    normalize_review_note,
)


class LinkAlertNotFoundError(RuntimeError):
    pass


def upsert_pending_link_alert(
    db: Session,
    *,
    user_id: int,
    source_id: int,
    external_event_id: str,
    entity_uid: str,
    link_id: int | None,
    evidence_snapshot: dict,
) -> EventLinkAlert:
    row = db.scalar(
        select(EventLinkAlert).where(
            EventLinkAlert.user_id == user_id,
            EventLinkAlert.source_id == source_id,
            EventLinkAlert.external_event_id == external_event_id,
            EventLinkAlert.entity_uid == entity_uid,
        )
    )
    if row is None:
        row = EventLinkAlert(
            user_id=user_id,
            source_id=source_id,
            external_event_id=external_event_id,
            entity_uid=entity_uid,
            link_id=link_id,
            risk_level=EventLinkAlertRiskLevel.MEDIUM,
            reason_code=EventLinkAlertReason.AUTO_LINK_WITHOUT_CANONICAL_CHANGE,
            status=EventLinkAlertStatus.PENDING,
            resolution_code=None,
            evidence_snapshot_json=evidence_snapshot if isinstance(evidence_snapshot, dict) else {},
            reviewed_by_user_id=None,
            reviewed_at=None,
            review_note=None,
        )
        db.add(row)
        return row

    row.link_id = link_id
    row.risk_level = EventLinkAlertRiskLevel.MEDIUM
    row.reason_code = EventLinkAlertReason.AUTO_LINK_WITHOUT_CANONICAL_CHANGE
    row.status = EventLinkAlertStatus.PENDING
    row.resolution_code = None
    row.evidence_snapshot_json = evidence_snapshot if isinstance(evidence_snapshot, dict) else {}
    row.reviewed_by_user_id = None
    row.reviewed_at = None
    row.review_note = None
    return row


def resolve_pending_link_alerts_for_pair(
    db: Session,
    *,
    user_id: int,
    source_id: int,
    external_event_id: str,
    resolution_code: EventLinkAlertResolution,
    note: str | None = None,
) -> int:
    rows = db.scalars(
        select(EventLinkAlert).where(
            EventLinkAlert.user_id == user_id,
            EventLinkAlert.source_id == source_id,
            EventLinkAlert.external_event_id == external_event_id,
            EventLinkAlert.status == EventLinkAlertStatus.PENDING,
        )
    ).all()
    return _resolve_rows(rows=rows, resolution_code=resolution_code, note=note)


def resolve_pending_link_alerts_for_entities(
    db: Session,
    *,
    user_id: int,
    entity_uids: set[str],
    resolution_code: EventLinkAlertResolution,
    note: str | None = None,
) -> int:
    normalized = {uid.strip() for uid in entity_uids if isinstance(uid, str) and uid.strip()}
    if not normalized:
        return 0
    rows = db.scalars(
        select(EventLinkAlert).where(
            EventLinkAlert.user_id == user_id,
            EventLinkAlert.entity_uid.in_(sorted(normalized)),
            EventLinkAlert.status == EventLinkAlertStatus.PENDING,
        )
    ).all()
    return _resolve_rows(rows=rows, resolution_code=resolution_code, note=note)


def _resolve_rows(
    *,
    rows: list[EventLinkAlert],
    resolution_code: EventLinkAlertResolution,
    note: str | None,
) -> int:
    if not rows:
        return 0
    now = datetime.now(timezone.utc)
    normalized_note = note.strip()[:512] if isinstance(note, str) and note.strip() else None
    for row in rows:
        row.status = EventLinkAlertStatus.RESOLVED
        row.resolution_code = resolution_code
        row.reviewed_at = now
        row.review_note = normalized_note
        row.reviewed_by_user_id = None
    return len(rows)


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
                "linked_entity": load_entity_preview(db=db, user_id=user_id, entity_uid=row.entity_uid),
            }
        )
    return out


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

    now = datetime.now(timezone.utc)
    row.status = EventLinkAlertStatus.DISMISSED
    row.resolution_code = EventLinkAlertResolution.DISMISSED_BY_USER
    row.reviewed_by_user_id = user_id
    row.reviewed_at = now
    row.review_note = normalize_review_note(note)
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

    now = datetime.now(timezone.utc)
    row.status = EventLinkAlertStatus.MARKED_SAFE
    row.resolution_code = EventLinkAlertResolution.MARKED_SAFE_BY_USER
    row.reviewed_by_user_id = user_id
    row.reviewed_at = now
    row.review_note = normalize_review_note(note)
    db.commit()
    db.refresh(row)
    return row, False


def batch_decide_link_alerts(
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
                build_batch_result_success(
                    item_id=alert_id,
                    status=row.status.value,
                    idempotent=idempotent,
                    extras={
                        "reviewed_at": row.reviewed_at,
                        "review_note": row.review_note,
                        "error_code": None,
                        "error_detail": None,
                    },
                )
            )
            succeeded += 1
        except LinkAlertNotFoundError as exc:
            results.append(
                build_batch_result_error(
                    item_id=alert_id,
                    error_code="not_found",
                    error_detail=str(exc),
                    extras={"reviewed_at": None, "review_note": None},
                )
            )
    failed = len(results) - succeeded
    return {
        "decision": decision,
        "total_requested": len(deduped_ids),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }
