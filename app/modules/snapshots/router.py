from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import require_api_key
from app.db.models import Snapshot
from app.db.session import get_db
from app.modules.snapshots.schemas import SnapshotResponse

router = APIRouter(prefix="/v1/snapshots", tags=["snapshots"], dependencies=[Depends(require_api_key)])


@router.get("", response_model=list[SnapshotResponse])
def list_snapshots(
    input_id: int = Query(..., ge=1),
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[SnapshotResponse]:
    settings = get_settings()
    applied_limit = limit or settings.default_changes_limit
    applied_limit = min(applied_limit, settings.max_changes_limit)

    stmt = (
        select(Snapshot)
        .where(Snapshot.input_id == input_id)
        .order_by(Snapshot.retrieved_at.desc(), Snapshot.id.desc())
        .offset(offset)
        .limit(applied_limit)
    )
    rows = db.scalars(stmt).all()

    return [
        SnapshotResponse(
            id=row.id,
            input_id=row.input_id,
            retrieved_at=row.retrieved_at,
            content_hash=row.content_hash,
            event_count=row.event_count,
            raw_evidence_key=row.raw_evidence_key,
        )
        for row in rows
    ]
