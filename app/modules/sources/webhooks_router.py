from __future__ import annotations

import hashlib
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.input import IngestTriggerType
from app.db.models.shared import User
from app.db.session import get_db
from app.modules.auth.deps import get_authenticated_user_or_401
from app.modules.common.request_rate_limit import enforce_user_mutation_rate_limit
from app.modules.sources.router_common import require_owned_source_or_404
from app.modules.sources.schemas import WebhookEnqueueResponse
from app.modules.sources.sync_requests_service import enqueue_sync_request_idempotent

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/sources/{source_id}/webhooks/{provider}", response_model=WebhookEnqueueResponse)
async def webhook_ingest(
    request: Request,
    source_id: int,
    provider: str,
    db: Session = Depends(get_db),
    x_event_id: str | None = Header(default=None, alias="X-Event-Id"),
    user: User = Depends(get_authenticated_user_or_401),
) -> WebhookEnqueueResponse:
    enforce_user_mutation_rate_limit(request, user_id=user.id)
    source = require_owned_source_or_404(db=db, user_id=user.id, source_id=source_id)

    normalized_provider = provider.strip().lower()
    if source.provider != normalized_provider:
        raise HTTPException(status_code=422, detail="provider mismatch")

    body = await request.body()
    max_body_bytes = max(int(get_settings().webhook_max_body_bytes), 0)
    if max_body_bytes > 0 and len(body) > max_body_bytes:
        logger.warning(
            "webhook payload rejected source_id=%s provider=%s body_bytes=%s max_body_bytes=%s",
            source.id,
            normalized_provider,
            len(body),
            max_body_bytes,
        )
        raise HTTPException(status_code=413, detail="webhook payload too large")
    event_id = x_event_id or hashlib.sha256(body).hexdigest()
    metadata: dict[str, object] = {
        "provider": normalized_provider,
        "event_id": event_id,
        "body_sha256": hashlib.sha256(body).hexdigest(),
    }
    preview_max_bytes = max(int(get_settings().webhook_metadata_preview_max_bytes), 0)
    preview_text = body[:preview_max_bytes].decode("utf-8", errors="replace") if preview_max_bytes > 0 else ""
    if preview_text:
        try:
            compact_json = json.dumps(json.loads(preview_text), ensure_ascii=False, separators=(",", ":"))
            metadata["payload_preview"] = compact_json[:preview_max_bytes]
        except Exception:
            metadata["payload_preview"] = preview_text
        metadata["payload_preview_truncated"] = len(body) > preview_max_bytes
    if request.headers.get("content-type"):
        metadata["content_type"] = request.headers.get("content-type")

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
