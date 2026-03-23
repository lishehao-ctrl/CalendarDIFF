from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.modules.sources.source_runtime_state import derive_source_runtime_state
from app.modules.sources.source_serializers import serialize_source
from app.modules.sources.status_projection import (
    build_source_observability_payload,
    build_sync_progress_payload,
    get_display_sync_request_for_source,
)


def build_source_read_payload(db: Session, *, source: InputSource) -> dict:
    runtime_state = derive_source_runtime_state(db, source=source)
    active_sync = get_display_sync_request_for_source(db, source_id=source.id)
    observability = build_source_observability_payload(db, source_id=source.id)
    sync_progress = build_sync_progress_payload(db, sync_request=active_sync) if active_sync is not None else None
    return serialize_source(
        source,
        runtime_state=runtime_state,
        active_request_id=active_sync.request_id if active_sync is not None else None,
        sync_progress=sync_progress,
        operator_guidance=observability.get("operator_guidance"),
        source_product_phase=observability.get("source_product_phase"),
        source_recovery=observability.get("source_recovery"),
    )


__all__ = ["build_source_read_payload"]
