from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models.runtime import CalendarComponentParseTask, IngestUnresolvedRecord
from app.db.models.input import IngestTriggerType, InputSource
from app.db.models.review import Change, ChangeSourceRef, SourceEventObservation
from app.modules.common.source_monitoring_window import SourceMonitoringWindow, source_timezone_name
from app.modules.runtime.apply.pending_proposal_rebuild import rebuild_pending_change_proposals
from app.modules.sources.sync_requests_service import enqueue_sync_request_idempotent_in_txn


@dataclass(frozen=True)
class SourceMonitoringWindowRescopeOutcome:
    affected_entity_uids: set[str]
    changes_created: int
    pending_entity_uids: set[str]
    sync_request_id: str | None


def monitoring_window_changed(
    *,
    previous: SourceMonitoringWindow | None,
    current: SourceMonitoringWindow | None,
) -> bool:
    if previous is None or current is None:
        return previous != current
    return previous.monitor_since != current.monitor_since


def apply_source_monitoring_window_rescope(
    *,
    db: Session,
    source: InputSource,
    monitoring_window: SourceMonitoringWindow,
    applied_at: datetime,
) -> SourceMonitoringWindowRescopeOutcome:
    affected_entity_uids = _collect_affected_entity_uids(db=db, source=source)
    _purge_source_scoped_state(db=db, source=source)

    changes_created = 0
    pending_entity_uids: set[str] = set()
    if affected_entity_uids:
        changes_created, pending_entity_uids = rebuild_pending_change_proposals(
            db=db,
            user_id=source.user_id,
            source=source,
            affected_entity_uids=affected_entity_uids,
            applied_at=applied_at,
        )

    sync_request_id: str | None = None
    timezone_name = source_timezone_name(source)
    if source.is_active and monitoring_window.has_started(now=applied_at, timezone_name=timezone_name):
        sync_request = enqueue_sync_request_idempotent_in_txn(
            db,
            source=source,
            trigger_type=IngestTriggerType.MANUAL,
            idempotency_key=f"monitoring_window_rescope:{source.id}:{monitoring_window.monitor_since.isoformat()}",
            metadata={
                "kind": "monitoring_window_rescope",
                "monitor_since": monitoring_window.monitor_since.isoformat(),
            },
            trace_id=f"monitoring-window-rescope:{source.id}",
        )
        sync_request_id = sync_request.request_id

    return SourceMonitoringWindowRescopeOutcome(
        affected_entity_uids=affected_entity_uids,
        changes_created=changes_created,
        pending_entity_uids=pending_entity_uids,
        sync_request_id=sync_request_id,
    )


def _collect_affected_entity_uids(*, db: Session, source: InputSource) -> set[str]:
    entity_uids: set[str] = set()

    entity_uids.update(
        value
        for value in db.scalars(
            select(SourceEventObservation.entity_uid).where(SourceEventObservation.source_id == source.id)
        ).all()
        if isinstance(value, str) and value
    )
    entity_uids.update(
        value
        for value in db.scalars(
            select(Change.entity_uid)
            .join(ChangeSourceRef, ChangeSourceRef.change_id == Change.id)
            .where(
                Change.user_id == source.user_id,
                ChangeSourceRef.source_id == source.id,
            )
            .distinct()
        ).all()
        if isinstance(value, str) and value
    )
    return entity_uids


def _purge_source_scoped_state(*, db: Session, source: InputSource) -> None:
    db.execute(delete(IngestUnresolvedRecord).where(IngestUnresolvedRecord.source_id == source.id))
    db.execute(delete(CalendarComponentParseTask).where(CalendarComponentParseTask.source_id == source.id))
    db.execute(delete(SourceEventObservation).where(SourceEventObservation.source_id == source.id))

    if source.cursor is not None:
        source.cursor.cursor_json = {}
    source.last_error_code = None
    source.last_error_message = None


__all__ = [
    "SourceMonitoringWindowRescopeOutcome",
    "apply_source_monitoring_window_rescope",
    "monitoring_window_changed",
]
