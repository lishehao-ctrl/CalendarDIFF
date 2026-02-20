from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.security import require_api_key
from app.db.models import Change
from app.db.session import get_db
from app.modules.changes.schemas import ChangeResponse

router = APIRouter(prefix="/v1/changes", tags=["changes"], dependencies=[Depends(require_api_key)])


@router.get("", response_model=list[ChangeResponse])
def list_changes(
    source_id: int | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[ChangeResponse]:
    settings = get_settings()
    applied_limit = limit or settings.default_changes_limit
    applied_limit = min(applied_limit, settings.max_changes_limit)

    stmt = select(Change).options(
        joinedload(Change.before_snapshot),
        joinedload(Change.after_snapshot),
    )
    if source_id is not None:
        stmt = stmt.where(Change.source_id == source_id)
    stmt = stmt.order_by(Change.detected_at.desc()).offset(offset).limit(applied_limit)

    rows = db.scalars(stmt).all()
    return [
        ChangeResponse(
            id=row.id,
            source_id=row.source_id,
            event_uid=row.event_uid,
            change_type=row.change_type.value,
            detected_at=row.detected_at,
            before_json=row.before_json,
            after_json=row.after_json,
            delta_seconds=row.delta_seconds,
            before_snapshot_id=row.before_snapshot_id,
            after_snapshot_id=row.after_snapshot_id,
            evidence_keys=row.evidence_keys,
            before_raw_evidence_key=row.before_snapshot.raw_evidence_key if row.before_snapshot else None,
            after_raw_evidence_key=row.after_snapshot.raw_evidence_key if row.after_snapshot else None,
        )
        for row in rows
    ]
