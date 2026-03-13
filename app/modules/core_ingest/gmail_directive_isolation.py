from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.modules.core_ingest.unresolved_store import upsert_active_unresolved_record


def isolate_directive_record(
    *,
    db: Session,
    source: InputSource,
    external_event_id: str,
    request_id: str,
    reason_code: str,
    source_facts: dict,
    payload: dict,
) -> None:
    upsert_active_unresolved_record(
        db=db,
        user_id=source.user_id,
        source_id=source.id,
        source_kind=source.source_kind,
        provider=source.provider,
        external_event_id=external_event_id,
        request_id=request_id,
        reason_code=reason_code,
        source_facts_json=source_facts,
        semantic_event_draft_json=None,
        kind_resolution_json={
            "status": "directive_isolated",
            "reason_code": reason_code,
        },
        raw_payload_json=payload,
    )


__all__ = ["isolate_directive_record"]
