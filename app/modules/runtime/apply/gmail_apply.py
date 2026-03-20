from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.models.review import ChangeIntakePhase
from app.db.models.review import Change
from app.modules.runtime.apply.apply_outcome import ApplyOutcome
from app.modules.runtime.apply.gmail_apply_atomic_lane import apply_gmail_atomic_record
from app.modules.runtime.apply.gmail_apply_directive_lane import apply_gmail_directive_record
from app.modules.runtime.apply.pending_change_outbox import emit_change_pending_created_event


def apply_gmail_observations(
    *,
    db: Session,
    source: InputSource,
    records: list[dict],
    applied_at: datetime,
    request_id: str,
    intake_phase: ChangeIntakePhase,
) -> ApplyOutcome:
    affected_entity_uids: set[str] = set()
    directive_created_changes: list[Change] = []

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        record_type = record.get("record_type")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if record_type == "gmail.message.extracted":
            changed_uids = apply_gmail_atomic_record(
                db=db,
                source=source,
                payload=payload,
                record_index=index,
                applied_at=applied_at,
                request_id=request_id,
            )
            affected_entity_uids.update(changed_uids)
            continue
        if record_type == "gmail.directive.extracted":
            created_changes = apply_gmail_directive_record(
                db=db,
                source=source,
                payload=payload,
                record_index=index,
                applied_at=applied_at,
                request_id=request_id,
                intake_phase=intake_phase,
            )
            directive_created_changes.extend(created_changes)

    if directive_created_changes:
        db.flush()
        emit_change_pending_created_event(
            db=db,
            user_id=source.user_id,
            changes=directive_created_changes,
            detected_at=applied_at,
        )

    return ApplyOutcome(
        affected_entity_uids=affected_entity_uids,
        direct_changes_created=len(directive_created_changes),
    )


__all__ = ["apply_gmail_observations"]
