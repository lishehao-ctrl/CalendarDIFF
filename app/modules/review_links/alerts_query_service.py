from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import EventLinkAlert, EventLinkAlertStatus
from app.modules.review_links.common import load_entity_preview


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


__all__ = ["list_link_alerts"]
