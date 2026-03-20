from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.runtime import IngestUnresolvedRecord
from app.db.models.input import SourceKind


def upsert_active_unresolved_record(
    *,
    db: Session,
    user_id: int,
    source_id: int,
    source_kind: SourceKind,
    provider: str,
    external_event_id: str,
    request_id: str | None,
    reason_code: str,
    source_facts_json: dict | None,
    semantic_event_draft_json: dict | None,
    kind_resolution_json: dict | None,
    raw_payload_json: dict | None,
) -> IngestUnresolvedRecord:
    existing = db.scalar(
        select(IngestUnresolvedRecord)
        .where(
            IngestUnresolvedRecord.user_id == user_id,
            IngestUnresolvedRecord.source_id == source_id,
            IngestUnresolvedRecord.external_event_id == external_event_id,
            IngestUnresolvedRecord.is_active.is_(True),
        )
        .order_by(IngestUnresolvedRecord.id.desc())
        .limit(1)
        .with_for_update()
    )
    if existing is not None:
        existing.request_id = request_id
        existing.reason_code = reason_code[:64]
        existing.source_facts_json = dict(source_facts_json) if isinstance(source_facts_json, dict) else {}
        existing.semantic_event_draft_json = (
            dict(semantic_event_draft_json) if isinstance(semantic_event_draft_json, dict) else None
        )
        existing.kind_resolution_json = dict(kind_resolution_json) if isinstance(kind_resolution_json, dict) else None
        existing.raw_payload_json = dict(raw_payload_json) if isinstance(raw_payload_json, dict) else None
        existing.resolved_at = None
        existing.is_active = True
        return existing

    row = IngestUnresolvedRecord(
        user_id=user_id,
        source_id=source_id,
        source_kind=source_kind,
        provider=provider,
        external_event_id=external_event_id[:255],
        request_id=request_id,
        reason_code=reason_code[:64],
        source_facts_json=dict(source_facts_json) if isinstance(source_facts_json, dict) else {},
        semantic_event_draft_json=dict(semantic_event_draft_json) if isinstance(semantic_event_draft_json, dict) else None,
        kind_resolution_json=dict(kind_resolution_json) if isinstance(kind_resolution_json, dict) else None,
        raw_payload_json=dict(raw_payload_json) if isinstance(raw_payload_json, dict) else None,
        is_active=True,
        resolved_at=None,
    )
    db.add(row)
    return row


def resolve_active_unresolved_records(
    *,
    db: Session,
    user_id: int,
    source_id: int,
    external_event_id: str,
    resolved_at: datetime,
) -> int:
    rows = list(
        db.scalars(
            select(IngestUnresolvedRecord)
            .where(
                IngestUnresolvedRecord.user_id == user_id,
                IngestUnresolvedRecord.source_id == source_id,
                IngestUnresolvedRecord.external_event_id == external_event_id,
                IngestUnresolvedRecord.is_active.is_(True),
            )
            .with_for_update()
        ).all()
    )
    for row in rows:
        row.is_active = False
        row.resolved_at = resolved_at
    return len(rows)


__all__ = [
    "resolve_active_unresolved_records",
    "upsert_active_unresolved_record",
]
