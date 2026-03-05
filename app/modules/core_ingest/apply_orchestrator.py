from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.ingestion import ConnectorResultStatus, IngestResult
from app.db.models.input import InputSource, SourceKind
from app.db.models.review import EventLinkAlertResolution, Input, InputType
from app.modules.core_ingest.calendar_apply import apply_calendar_observations
from app.modules.core_ingest.gmail_apply import apply_gmail_observations
from app.modules.core_ingest.link_alert_outbox import emit_link_alert_resolve_entities_requested
from app.modules.core_ingest.pending_auto_link_alerts import upsert_auto_link_alerts_without_pending
from app.modules.core_ingest.pending_proposal_rebuild import rebuild_pending_change_proposals


def ensure_canonical_input_for_user(*, db: Session, user_id: int) -> Input:
    identity_key = f"canonical:user:{user_id}"
    input_row = db.scalar(
        select(Input).where(
            Input.user_id == user_id,
            Input.type == InputType.ICS,
            Input.identity_key == identity_key,
        )
    )
    if input_row is not None:
        return input_row

    input_row = Input(
        user_id=user_id,
        type=InputType.ICS,
        identity_key=identity_key,
        is_active=True,
    )
    db.add(input_row)
    db.flush()
    return input_row


def apply_records(
    *,
    db: Session,
    result: IngestResult,
    source: InputSource,
    applied_at: datetime,
    request_id: str,
) -> int:
    records = result.records if isinstance(result.records, list) else []
    auto_link_contexts: list[dict] = []

    if result.status == ConnectorResultStatus.NO_CHANGE and not records:
        return 0

    canonical_input = ensure_canonical_input_for_user(db=db, user_id=source.user_id)

    if source.source_kind == SourceKind.CALENDAR:
        affected_merge_keys = apply_calendar_observations(
            db=db,
            source=source,
            records=records,
            applied_at=applied_at,
            request_id=request_id,
        )
    elif source.source_kind == SourceKind.EMAIL:
        affected_merge_keys = apply_gmail_observations(
            db=db,
            source=source,
            records=records,
            applied_at=applied_at,
            request_id=request_id,
            auto_link_contexts=auto_link_contexts,
        )
    else:
        return 0

    if not affected_merge_keys:
        return 0

    db.flush()
    changes_created, pending_event_uids = rebuild_pending_change_proposals(
        db=db,
        source=source,
        canonical_input=canonical_input,
        affected_merge_keys=affected_merge_keys,
        applied_at=applied_at,
    )
    emit_link_alert_resolve_entities_requested(
        db=db,
        user_id=source.user_id,
        entity_uids=pending_event_uids,
        resolution_code=EventLinkAlertResolution.CANONICAL_PENDING_CREATED,
        note="canonical_pending_created",
    )
    if source.source_kind == SourceKind.EMAIL and auto_link_contexts:
        upsert_auto_link_alerts_without_pending(
            db=db,
            auto_link_contexts=auto_link_contexts,
            pending_event_uids=pending_event_uids,
        )
    return changes_created


__all__ = ["apply_records", "ensure_canonical_input_for_user"]
