from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models.ingestion import ConnectorResultStatus
from app.db.models.input import InputSource, SourceKind
from app.db.models.review import EventEntity, EventEntityLink, EventLinkAlert, EventLinkBlock, EventLinkCandidate, Input, InputType, ReviewStatus, SourceEventObservation
from app.db.models.shared import User
from app.modules.core_ingest.apply_orchestrator import apply_records
from app.modules.users.work_item_kind_mappings_service import mark_user_work_item_mapping_rebuild_complete, mark_user_work_item_mapping_rebuild_failed, mark_user_work_item_mapping_rebuild_running


def rebuild_user_work_item_state(db: Session, *, user: User) -> None:
    mark_user_work_item_mapping_rebuild_running(db, user=user)
    try:
        _clear_user_derived_state(db, user_id=user.id)
        now = datetime.now(timezone.utc)
        sources = list(
            db.scalars(
                select(InputSource)
                .where(InputSource.user_id == user.id, InputSource.is_active.is_(True))
                .order_by(InputSource.source_kind.asc(), InputSource.id.asc())
            ).all()
        )
        # calendar first
        sources.sort(key=lambda row: (0 if row.source_kind == SourceKind.CALENDAR else 1, row.id))
        for source in sources:
            observations = list(
                db.scalars(
                    select(SourceEventObservation)
                    .where(
                        SourceEventObservation.user_id == user.id,
                        SourceEventObservation.source_id == source.id,
                        SourceEventObservation.is_active.is_(True),
                    )
                    .order_by(SourceEventObservation.observed_at.asc(), SourceEventObservation.id.asc())
                ).all()
            )
            if not observations:
                continue
            records: list[dict] = []
            record_type = "calendar.event.extracted" if source.source_kind == SourceKind.CALENDAR else "gmail.message.extracted"
            for row in observations:
                payload = _rebuild_payload_from_observation(source_kind=source.source_kind, external_event_id=row.external_event_id, payload=row.event_payload)
                records.append({"record_type": record_type, "payload": payload})
            pseudo_result = SimpleNamespace(records=records, status=ConnectorResultStatus.CHANGED)
            request_id = f"rebuild:user:{user.id}:source:{source.id}:{int(now.timestamp())}"
            apply_records(db=db, result=pseudo_result, source=source, applied_at=now, request_id=request_id)
        db.commit()
        mark_user_work_item_mapping_rebuild_complete(db, user=user)
    except Exception as exc:
        db.rollback()
        mark_user_work_item_mapping_rebuild_failed(db, user=user, error=str(exc))
        raise


def _clear_user_derived_state(db: Session, *, user_id: int) -> None:
    canonical_input = db.scalar(
        select(Input).where(
            Input.user_id == user_id,
            Input.type == InputType.ICS,
            Input.identity_key == f"canonical:user:{user_id}",
        )
    )
    if canonical_input is not None:
        db.delete(canonical_input)
        db.flush()
    db.execute(delete(EventLinkAlert).where(EventLinkAlert.user_id == user_id))
    db.execute(delete(EventLinkCandidate).where(EventLinkCandidate.user_id == user_id))
    db.execute(delete(EventLinkBlock).where(EventLinkBlock.user_id == user_id))
    db.execute(delete(EventEntityLink).where(EventEntityLink.user_id == user_id))
    db.execute(delete(EventEntity).where(EventEntity.user_id == user_id))
    db.flush()


__all__ = ["rebuild_user_work_item_state"]


def _rebuild_payload_from_observation(*, source_kind: SourceKind, external_event_id: str, payload: object) -> dict:
    raw = payload if isinstance(payload, dict) else {}
    source_canonical_raw = raw.get("source_canonical")
    source_canonical = dict(source_canonical_raw) if isinstance(source_canonical_raw, dict) else {}
    enrichment_raw = raw.get("enrichment")
    enrichment = dict(enrichment_raw) if isinstance(enrichment_raw, dict) else {}
    rebuilt: dict = {
        "source_canonical": source_canonical,
        "enrichment": enrichment,
    }
    if source_kind == SourceKind.EMAIL:
        rebuilt["message_id"] = external_event_id
    if source_kind == SourceKind.CALENDAR and isinstance(raw.get("raw_ics_component_b64"), str):
        rebuilt["raw_ics_component_b64"] = raw["raw_ics_component_b64"]
    return rebuilt
