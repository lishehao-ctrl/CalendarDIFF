from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import sanitize_log_message
from app.db.models.review import EventLinkAlertResolution
from app.db.models.shared import IntegrationInbox, IntegrationOutbox, OutboxStatus
from app.modules.review_links.alerts_upsert_service import (
    resolve_pending_link_alerts_for_entities,
    resolve_pending_link_alerts_for_pair,
    upsert_pending_link_alert,
)

REVIEW_LINK_ALERTS_CONSUMER = "review.link_alerts.consumer.v1"
REVIEW_LINK_ALERTS_BATCH_SIZE = 200
REVIEW_LINK_ALERTS_EVENT_TYPES = {
    "review.link_alert.upsert.requested",
    "review.link_alert.resolve_pair.requested",
    "review.link_alert.resolve_entities.requested",
}


def run_review_link_alert_events_tick(db: Session, *, batch_limit: int = REVIEW_LINK_ALERTS_BATCH_SIZE) -> int:
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(IntegrationOutbox)
        .where(
            IntegrationOutbox.status == OutboxStatus.PENDING,
            IntegrationOutbox.event_type.in_(sorted(REVIEW_LINK_ALERTS_EVENT_TYPES)),
            IntegrationOutbox.available_at <= now,
        )
        .order_by(IntegrationOutbox.id.asc())
        .with_for_update(skip_locked=True)
        .limit(max(1, int(batch_limit)))
    ).all()

    processed = 0
    for row in rows:
        payload = row.payload_json if isinstance(row.payload_json, dict) else {}
        try:
            db.add(
                IntegrationInbox(
                    consumer_name=REVIEW_LINK_ALERTS_CONSUMER,
                    event_id=row.event_id,
                    payload_json=payload,
                )
            )
            db.flush()
        except IntegrityError:
            db.rollback()
            row_in_db = db.get(IntegrationOutbox, row.id)
            if row_in_db is not None:
                row_in_db.status = OutboxStatus.PROCESSED
                row_in_db.processed_at = now
                db.commit()
            processed += 1
            continue

        try:
            _apply_link_alert_event(
                db,
                event_type=row.event_type,
                payload=payload,
            )
            row.status = OutboxStatus.PROCESSED
            row.processed_at = now
            db.commit()
        except Exception as exc:
            db.rollback()
            row_in_db = db.get(IntegrationOutbox, row.id)
            if row_in_db is not None:
                row_in_db.status = OutboxStatus.FAILED
                row_in_db.attempt += 1
                row_in_db.last_error = sanitize_log_message(str(exc))[:512]
                db.commit()
        processed += 1
    return processed


def _apply_link_alert_event(db: Session, *, event_type: str, payload: dict) -> None:
    if event_type == "review.link_alert.upsert.requested":
        user_id = _require_int(payload, "user_id")
        source_id = _require_int(payload, "source_id")
        external_event_id = _require_str(payload, "external_event_id")
        entity_uid = _require_str(payload, "entity_uid")
        link_id = payload.get("link_id")
        if link_id is not None and not isinstance(link_id, int):
            raise ValueError("link_id must be int or null")
        evidence_snapshot_raw = payload.get("evidence_snapshot")
        evidence_snapshot = evidence_snapshot_raw if isinstance(evidence_snapshot_raw, dict) else {}
        upsert_pending_link_alert(
            db=db,
            user_id=user_id,
            source_id=source_id,
            external_event_id=external_event_id,
            entity_uid=entity_uid,
            link_id=link_id,
            evidence_snapshot=evidence_snapshot,
        )
        return

    if event_type == "review.link_alert.resolve_pair.requested":
        user_id = _require_int(payload, "user_id")
        source_id = _require_int(payload, "source_id")
        external_event_id = _require_str(payload, "external_event_id")
        resolution_code = EventLinkAlertResolution(_require_str(payload, "resolution_code"))
        note = payload.get("note") if isinstance(payload.get("note"), str) else None
        resolve_pending_link_alerts_for_pair(
            db=db,
            user_id=user_id,
            source_id=source_id,
            external_event_id=external_event_id,
            resolution_code=resolution_code,
            note=note,
        )
        return

    if event_type == "review.link_alert.resolve_entities.requested":
        user_id = _require_int(payload, "user_id")
        resolution_code = EventLinkAlertResolution(_require_str(payload, "resolution_code"))
        note = payload.get("note") if isinstance(payload.get("note"), str) else None
        entity_uids_raw = payload.get("entity_uids")
        if not isinstance(entity_uids_raw, list):
            raise ValueError("entity_uids must be list[str]")
        entity_uids = {item.strip() for item in entity_uids_raw if isinstance(item, str) and item.strip()}
        resolve_pending_link_alerts_for_entities(
            db=db,
            user_id=user_id,
            entity_uids=entity_uids,
            resolution_code=resolution_code,
            note=note,
        )
        return

    raise ValueError(f"unsupported link alert event_type: {event_type}")


def _require_int(payload: dict, key: str) -> int:
    value = payload.get(key)
    if isinstance(value, int):
        return value
    raise ValueError(f"{key} must be int")


def _require_str(payload: dict, key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError(f"{key} must be non-empty string")


__all__ = ["run_review_link_alert_events_tick"]
