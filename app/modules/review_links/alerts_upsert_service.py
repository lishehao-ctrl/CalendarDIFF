from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import EventLinkAlert, EventLinkAlertReason, EventLinkAlertResolution, EventLinkAlertRiskLevel, EventLinkAlertStatus


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
    rows: Sequence[EventLinkAlert],
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


__all__ = [
    "resolve_pending_link_alerts_for_entities",
    "resolve_pending_link_alerts_for_pair",
    "upsert_pending_link_alert",
]
