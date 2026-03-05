from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    ConnectorResultStatus,
    EventLinkAlertResolution,
    IngestApplyLog,
    IngestResult,
    InputSource,
    SourceKind,
    SyncRequest,
    SyncRequestStatus,
)
from app.modules.core_ingest.pending_rebuild import (
    rebuild_pending_change_proposals,
    upsert_auto_link_alerts_without_pending,
)
from app.modules.core_ingest.records_apply import (
    apply_calendar_observations,
    apply_gmail_observations,
    ensure_canonical_input_for_user,
)
from app.modules.review_links.alerts_service import resolve_pending_link_alerts_for_entities


def get_ingest_apply_status(db: Session, *, request_id: str) -> dict:
    result = db.scalar(select(IngestResult).where(IngestResult.request_id == request_id))
    apply_log = db.scalar(select(IngestApplyLog).where(IngestApplyLog.request_id == request_id))
    return {
        "request_id": request_id,
        "result_exists": result is not None,
        "result_status": result.status.value if result is not None else None,
        "applied": apply_log is not None,
        "applied_at": apply_log.applied_at if apply_log is not None else None,
    }


def apply_ingest_result_idempotent(db: Session, *, request_id: str) -> dict:
    now = datetime.now(timezone.utc)
    result = db.scalar(select(IngestResult).where(IngestResult.request_id == request_id))
    if result is None:
        raise RuntimeError("Ingest result not found")

    sync_request = db.scalar(select(SyncRequest).where(SyncRequest.request_id == request_id))
    source = db.get(InputSource, result.source_id)
    if source is None:
        raise RuntimeError("Input source not found for ingest result")

    try:
        db.add(
            IngestApplyLog(
                request_id=request_id,
                applied_at=now,
                status="applied",
                error_message=None,
            )
        )
        db.flush()
    except IntegrityError:
        db.rollback()
        return {
            "request_id": request_id,
            "applied": True,
            "idempotent_replay": True,
            "changes_created": 0,
        }

    try:
        changes_created = apply_records(
            db=db,
            result=result,
            source=source,
            applied_at=now,
            request_id=request_id,
        )
        if sync_request is not None and sync_request.status != SyncRequestStatus.FAILED:
            sync_request.status = SyncRequestStatus.SUCCEEDED
            sync_request.error_code = None
            sync_request.error_message = None
        db.commit()
        return {
            "request_id": request_id,
            "applied": True,
            "idempotent_replay": False,
            "changes_created": changes_created,
        }
    except Exception:
        db.rollback()
        raise


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
    resolve_pending_link_alerts_for_entities(
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


__all__ = ["apply_ingest_result_idempotent", "apply_records", "get_ingest_apply_status"]
