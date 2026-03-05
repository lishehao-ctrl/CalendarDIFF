from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.models.input import IngestTriggerType
from app.db.session import get_db
from app.modules.input_control_plane.router_common import require_owned_source_or_404, require_registered_user_or_409
from app.modules.input_control_plane.schemas import WebhookEnqueueResponse
from app.modules.input_control_plane.sync_requests_service import enqueue_sync_request_idempotent

router = APIRouter()


@router.post("/sources/{source_id}/webhooks/{provider}", response_model=WebhookEnqueueResponse)
async def webhook_ingest(
    request: Request,
    source_id: int,
    provider: str,
    db: Session = Depends(get_db),
    x_event_id: str | None = Header(default=None, alias="X-Event-Id"),
) -> WebhookEnqueueResponse:
    user = require_registered_user_or_409(db)
    source = require_owned_source_or_404(db=db, user_id=user.id, source_id=source_id)

    normalized_provider = provider.strip().lower()
    if source.provider != normalized_provider:
        raise HTTPException(status_code=422, detail="provider mismatch")

    body = await request.body()
    event_id = x_event_id or hashlib.sha256(body).hexdigest()
    metadata: dict[str, object] = {
        "provider": normalized_provider,
        "event_id": event_id,
    }
    try:
        payload_json = json.loads(body.decode("utf-8")) if body else {}
        if isinstance(payload_json, dict):
            metadata["payload"] = payload_json
    except Exception:
        metadata["payload_raw"] = body.decode("utf-8", errors="replace")

    row = enqueue_sync_request_idempotent(
        db,
        source=source,
        trigger_type=IngestTriggerType.WEBHOOK,
        idempotency_key=f"webhook:{source.id}:{event_id}",
        metadata=metadata,
        trace_id=event_id,
    )
    return WebhookEnqueueResponse(request_id=row.request_id, status=row.status.value)


__all__ = ["router"]
