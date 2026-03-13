from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.core_ingest.link_alert_outbox import emit_link_alert_upsert_requested


def upsert_auto_link_alerts_without_pending(
    *,
    db: Session,
    auto_link_contexts: list[dict],
    pending_entity_uids: set[str],
) -> None:
    for context in auto_link_contexts:
        entity_uid = context.get("entity_uid")
        if not isinstance(entity_uid, str) or not entity_uid.strip():
            continue
        if entity_uid in pending_entity_uids:
            continue
        link_row = context.get("link_row")
        link_row_id = getattr(link_row, "id", None)
        link_id = int(link_row_id) if isinstance(link_row_id, int) else None
        evidence_snapshot_raw = context.get("evidence_snapshot")
        evidence_snapshot = evidence_snapshot_raw if isinstance(evidence_snapshot_raw, dict) else {}
        emit_link_alert_upsert_requested(
            db=db,
            user_id=int(context["user_id"]),
            source_id=int(context["source_id"]),
            external_event_id=str(context["external_event_id"]),
            entity_uid=entity_uid,
            link_id=link_id,
            evidence_snapshot=evidence_snapshot,
        )


__all__ = ["upsert_auto_link_alerts_without_pending"]
