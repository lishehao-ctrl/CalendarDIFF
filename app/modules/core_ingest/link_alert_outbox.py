from __future__ import annotations

from app.contracts.events import new_event
from app.db.models.review import EventLinkAlertResolution
from app.db.models.shared import IntegrationOutbox, OutboxStatus


def emit_link_alert_upsert_requested(
    *,
    db,
    user_id: int,
    source_id: int,
    external_event_id: str,
    entity_uid: str,
    link_id: int | None,
    evidence_snapshot: dict,
) -> None:
    event = new_event(
        event_type="review.link_alert.upsert.requested",
        aggregate_type="link_alert_request",
        aggregate_id=f"{user_id}:{source_id}:{external_event_id}:{entity_uid}",
        payload={
            "user_id": user_id,
            "source_id": source_id,
            "external_event_id": external_event_id,
            "entity_uid": entity_uid,
            "link_id": link_id,
            "evidence_snapshot": evidence_snapshot if isinstance(evidence_snapshot, dict) else {},
        },
    )
    db.add(
        IntegrationOutbox(
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload_json=event.payload,
            status=OutboxStatus.PENDING,
            available_at=event.available_at,
        )
    )


def emit_link_alert_resolve_pair_requested(
    *,
    db,
    user_id: int,
    source_id: int,
    external_event_id: str,
    resolution_code: EventLinkAlertResolution,
    note: str | None = None,
) -> None:
    event = new_event(
        event_type="review.link_alert.resolve_pair.requested",
        aggregate_type="link_alert_request",
        aggregate_id=f"{user_id}:{source_id}:{external_event_id}",
        payload={
            "user_id": user_id,
            "source_id": source_id,
            "external_event_id": external_event_id,
            "resolution_code": resolution_code.value,
            "note": note,
        },
    )
    db.add(
        IntegrationOutbox(
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload_json=event.payload,
            status=OutboxStatus.PENDING,
            available_at=event.available_at,
        )
    )


def emit_link_alert_resolve_entities_requested(
    *,
    db,
    user_id: int,
    entity_uids: set[str],
    resolution_code: EventLinkAlertResolution,
    note: str | None = None,
) -> None:
    normalized_entity_uids = sorted({uid.strip() for uid in entity_uids if isinstance(uid, str) and uid.strip()})
    if not normalized_entity_uids:
        return
    event = new_event(
        event_type="review.link_alert.resolve_entities.requested",
        aggregate_type="link_alert_request",
        aggregate_id=f"{user_id}:{resolution_code.value}:{len(normalized_entity_uids)}",
        payload={
            "user_id": user_id,
            "entity_uids": normalized_entity_uids,
            "resolution_code": resolution_code.value,
            "note": note,
        },
    )
    db.add(
        IntegrationOutbox(
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload_json=event.payload,
            status=OutboxStatus.PENDING,
            available_at=event.available_at,
        )
    )


__all__ = [
    "emit_link_alert_resolve_entities_requested",
    "emit_link_alert_resolve_pair_requested",
    "emit_link_alert_upsert_requested",
]
