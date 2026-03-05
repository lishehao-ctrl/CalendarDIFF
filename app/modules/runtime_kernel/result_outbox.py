from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.events import new_event
from app.db.models.ingestion import ConnectorResultStatus, IngestResult
from app.db.models.shared import IntegrationOutbox, OutboxStatus


def upsert_ingest_result_and_outbox_once(
    db: Session,
    *,
    request_id: str,
    source_id: int,
    provider: str,
    result_status: ConnectorResultStatus,
    cursor_patch: dict,
    records: list[dict],
    fetched_at: datetime,
) -> bool:
    existing_result = db.scalar(select(IngestResult).where(IngestResult.request_id == request_id))
    if existing_result is not None:
        return False

    db.add(
        IngestResult(
            request_id=request_id,
            source_id=source_id,
            provider=provider,
            status=result_status,
            cursor_patch=cursor_patch,
            records=records,
            fetched_at=fetched_at,
            error_code=None,
            error_message=None,
        )
    )
    event = new_event(
        event_type="ingest.result.ready",
        aggregate_type="ingest_result",
        aggregate_id=request_id,
        payload={
            "request_id": request_id,
            "source_id": source_id,
            "provider": provider,
            "status": result_status.value,
        },
    )
    db.add(
        IntegrationOutbox(
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload_json=event.payload,
            status=OutboxStatus.PENDING,
            available_at=event.available_at,
        )
    )
    return True


__all__ = ["upsert_ingest_result_and_outbox_once"]
