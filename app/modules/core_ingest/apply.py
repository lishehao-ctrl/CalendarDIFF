from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.ingestion import ConnectorResultStatus, IngestResult
from app.db.models.input import InputSource, InputSourceCursor, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.review import IngestApplyLog
from app.modules.core_ingest.apply_outcome import ApplyOutcome
from app.modules.core_ingest.calendar_apply import apply_calendar_observations
from app.modules.core_ingest.gmail_apply import apply_gmail_observations
from app.modules.core_ingest.pending_proposal_rebuild import rebuild_pending_change_proposals
from app.modules.input_control_plane.source_term_rebind import apply_pending_term_rebind_if_terminal


def apply_records(
    *,
    db: Session,
    result: IngestResult,
    source: InputSource,
    applied_at: datetime,
    request_id: str,
) -> int:
    records = result.records if isinstance(result.records, list) else []

    if result.status == ConnectorResultStatus.NO_CHANGE and not records:
        return 0

    previous_observation_payloads: dict[str, dict] | None = {} if source.source_kind == SourceKind.CALENDAR else None
    outcome = ApplyOutcome()

    if source.source_kind == SourceKind.CALENDAR:
        outcome = ApplyOutcome(
            affected_entity_uids=apply_calendar_observations(
                db=db,
                source=source,
                records=records,
                applied_at=applied_at,
                request_id=request_id,
                previous_observation_payloads=previous_observation_payloads,
            )
        )
    elif source.source_kind == SourceKind.EMAIL:
        outcome = apply_gmail_observations(
            db=db,
            source=source,
            records=records,
            applied_at=applied_at,
            request_id=request_id,
        )
    else:
        return 0

    if not outcome.affected_entity_uids:
        return outcome.direct_changes_created

    db.flush()
    changes_created, _pending_entity_uids = rebuild_pending_change_proposals(
        db=db,
        user_id=source.user_id,
        source=source,
        affected_entity_uids=outcome.affected_entity_uids,
        applied_at=applied_at,
        previous_observation_payloads=previous_observation_payloads,
    )
    return changes_created + outcome.direct_changes_created


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
        _apply_source_success_state(db=db, source=source, result=result, completed_at=now)
        if sync_request is not None and sync_request.status != SyncRequestStatus.FAILED:
            sync_request.status = SyncRequestStatus.SUCCEEDED
            sync_request.error_code = None
            sync_request.error_message = None
        apply_pending_term_rebind_if_terminal(
            db=db,
            source=source,
            terminal_status=SyncRequestStatus.SUCCEEDED,
            applied_at=now,
        )
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


def _apply_source_success_state(
    *,
    db: Session,
    source: InputSource,
    result: IngestResult,
    completed_at: datetime,
) -> None:
    cursor_patch = result.cursor_patch if isinstance(result.cursor_patch, dict) else {}
    if cursor_patch:
        if source.cursor is None:
            source.cursor = InputSourceCursor(source_id=source.id, version=1, cursor_json={})
            db.flush()
        merged = dict(source.cursor.cursor_json or {})
        merged.update(cursor_patch)
        source.cursor.cursor_json = merged
        source.cursor.version += 1

    source.last_polled_at = result.fetched_at
    source.next_poll_at = completed_at.astimezone(timezone.utc).replace(microsecond=0) + timedelta(
        seconds=max(int(source.poll_interval_seconds), 30)
    )
    source.last_error_code = None
    source.last_error_message = None


__all__ = [
    "apply_ingest_result_idempotent",
    "apply_records",
    "get_ingest_apply_status",
]
