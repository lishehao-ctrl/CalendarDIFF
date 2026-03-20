from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource, SyncRequest, SyncRequestStatus
from app.modules.common.source_term_window import parse_source_term_window, source_timezone_name
from app.modules.sources.source_term_rebind import has_pending_term_rebind

SourceLifecycleState = Literal["active", "inactive", "archived"]
SourceSyncState = Literal["idle", "queued", "running"]
SourceConfigState = Literal["stable", "rebind_pending"]
SourceRuntimeState = Literal["active", "inactive", "archived", "queued", "running", "rebind_pending"]

QUEUED_SYNC_STATUSES = (SyncRequestStatus.PENDING, SyncRequestStatus.QUEUED)
INFLIGHT_SYNC_STATUSES = (*QUEUED_SYNC_STATUSES, SyncRequestStatus.RUNNING)


@dataclass(frozen=True)
class SourceRuntimeStateProjection:
    lifecycle_state: SourceLifecycleState
    sync_state: SourceSyncState
    config_state: SourceConfigState
    runtime_state: SourceRuntimeState


def derive_source_runtime_state(db: Session, *, source: InputSource) -> SourceRuntimeStateProjection:
    return derive_source_runtime_states(db, sources=[source])[source.id]


def derive_source_runtime_states(
    db: Session,
    *,
    sources: list[InputSource],
) -> dict[int, SourceRuntimeStateProjection]:
    if not sources:
        return {}

    source_ids = [source.id for source in sources]
    running_source_ids: set[int] = set()
    queued_source_ids: set[int] = set()
    rows = db.execute(
        select(SyncRequest.source_id, SyncRequest.status).where(
            SyncRequest.source_id.in_(source_ids),
            SyncRequest.status.in_(INFLIGHT_SYNC_STATUSES),
        )
    ).all()
    for source_id, status in rows:
        if status == SyncRequestStatus.RUNNING:
            running_source_ids.add(int(source_id))
            continue
        queued_source_ids.add(int(source_id))

    now = datetime.now(timezone.utc)
    projections: dict[int, SourceRuntimeStateProjection] = {}
    for source in sources:
        lifecycle_state = _derive_lifecycle_state(source=source, now=now)
        sync_state: SourceSyncState
        if source.id in running_source_ids:
            sync_state = "running"
        elif source.id in queued_source_ids:
            sync_state = "queued"
        else:
            sync_state = "idle"
        config_state: SourceConfigState = "rebind_pending" if has_pending_term_rebind(source) else "stable"
        projections[source.id] = SourceRuntimeStateProjection(
            lifecycle_state=lifecycle_state,
            sync_state=sync_state,
            config_state=config_state,
            runtime_state=_derive_runtime_state(
                lifecycle_state=lifecycle_state,
                sync_state=sync_state,
                config_state=config_state,
            ),
        )
    return projections


def _derive_lifecycle_state(
    *,
    source: InputSource,
    now: datetime,
) -> SourceLifecycleState:
    term_window = parse_source_term_window(source, required=False)
    if term_window is not None and term_window.is_expired(now=now, timezone_name=source_timezone_name(source)):
        return "archived"
    if source.is_active:
        return "active"
    return "inactive"


def _derive_runtime_state(
    *,
    lifecycle_state: SourceLifecycleState,
    sync_state: SourceSyncState,
    config_state: SourceConfigState,
) -> SourceRuntimeState:
    if lifecycle_state == "archived":
        return "archived"
    if config_state == "rebind_pending":
        return "rebind_pending"
    if sync_state == "running":
        return "running"
    if sync_state == "queued":
        return "queued"
    if lifecycle_state == "inactive":
        return "inactive"
    return "active"


__all__ = [
    "SourceConfigState",
    "SourceLifecycleState",
    "SourceRuntimeState",
    "SourceRuntimeStateProjection",
    "SourceSyncState",
    "derive_source_runtime_state",
    "derive_source_runtime_states",
]
