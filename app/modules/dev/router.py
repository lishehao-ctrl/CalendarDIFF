from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import encrypt_secret, require_api_key
from app.db.models import (
    Change,
    ChangeType,
    Input,
    InputType,
    Notification,
    NotificationChannel,
    NotificationStatus,
    Snapshot,
)
from app.db.session import get_db
from app.modules.users.service import (
    UserNotInitializedError,
    UserOnboardingIncompleteError,
    require_onboarded_user,
    user_onboarding_incomplete_detail,
    user_not_initialized_detail,
)


class InjectActionItem(BaseModel):
    action: str | None = None
    due_iso: str | None = None
    where: str | None = None


class InjectNotifyRequest(BaseModel):
    email_id: str | None = None
    subject: str = Field(min_length=1)
    from_: str | None = Field(default=None, alias="from")
    date: str | None = None
    body_text: str = Field(min_length=1)
    course_hints: list[str] | None = None
    event_type: Literal[
        "deadline",
        "exam",
        "schedule_change",
        "assignment",
        "action_required",
        "announcement",
        "grade",
        "other",
    ] | None = None
    action_items: list[InjectActionItem] | None = None

    model_config = {"populate_by_name": True, "extra": "forbid"}


class InjectNotifyResponse(BaseModel):
    input_id: int
    snapshot_id: int
    change_id: int
    notification_id: int
    email_id: str
    ui_path: str


router = APIRouter(prefix="/v1/dev", tags=["dev"], dependencies=[Depends(require_api_key)])


@router.post("/inject_notify", response_model=InjectNotifyResponse)
def inject_notify(payload: InjectNotifyRequest, db: Session = Depends(get_db)) -> InjectNotifyResponse:
    settings = get_settings()
    if settings.app_env.lower() != "dev" or not settings.enable_dev_endpoints:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    try:
        user = require_onboarded_user(db)
    except UserNotInitializedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=user_not_initialized_detail()) from exc
    except UserOnboardingIncompleteError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=user_onboarding_incomplete_detail()) from exc
    input_row = _get_or_create_dev_email_input(db, user_id=user.id)

    email_id = payload.email_id.strip() if isinstance(payload.email_id, str) and payload.email_id.strip() else uuid4().hex
    now = datetime.now(timezone.utc)

    after_json = {
        "email_id": email_id,
        "subject": payload.subject,
        "from": payload.from_,
        "internal_date": payload.date,
        "snippet": payload.body_text[:240],
        "body_preview": payload.body_text[:1500],
        "course_hints": payload.course_hints or [],
        "event_type": payload.event_type,
        "action_items": [item.model_dump() for item in payload.action_items or []],
        "label": "KEEP",
        "confidence": 1.0,
        "reasons": ["dev inject"],
    }

    snapshot = Snapshot(
        input_id=input_row.id,
        retrieved_at=now,
        content_hash=hashlib.sha256(f"dev|{email_id}|{now.isoformat()}".encode("utf-8")).hexdigest(),
        event_count=1,
        raw_evidence_key={"kind": "dev", "path": f"dev://inject/{email_id}"},
    )
    db.add(snapshot)
    db.flush()

    change = Change(
        input_id=input_row.id,
        event_uid=email_id,
        change_type=ChangeType.CREATED,
        detected_at=now,
        before_json=None,
        after_json=after_json,
        delta_seconds=None,
        before_snapshot_id=None,
        after_snapshot_id=snapshot.id,
        evidence_keys={"after": snapshot.raw_evidence_key},
    )
    db.add(change)
    db.flush()

    notification = Notification(
        change_id=change.id,
        channel=NotificationChannel.EMAIL,
        status=NotificationStatus.PENDING,
        sent_at=None,
        notified_at=None,
        error=None,
        idempotency_key=f"dev:inject:{change.id}",
        deliver_after=now,
        enqueue_reason="digest_queue",
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)

    return InjectNotifyResponse(
        input_id=input_row.id,
        snapshot_id=snapshot.id,
        change_id=change.id,
        notification_id=notification.id,
        email_id=email_id,
        ui_path=f"/ui/feed?input_id={input_row.id}",
    )


def _get_or_create_dev_email_input(db: Session, *, user_id: int) -> Input:
    existing = db.query(Input).filter(Input.user_id == user_id, Input.type == InputType.EMAIL, Input.identity_key == "dev:inject:email").first()
    if existing is not None:
        return existing

    row = Input(
        user_id=user_id,
        user_term_id=None,
        type=InputType.EMAIL,
        identity_key="dev:inject:email",
        encrypted_url=encrypt_secret("dev://inject/email"),
        provider="dev",
        gmail_label="DEV_INJECT",
        gmail_from_contains=None,
        gmail_subject_keywords=None,
        gmail_history_id=None,
        gmail_account_email="dev-inject@example.com",
        encrypted_access_token=None,
        encrypted_refresh_token=None,
        access_token_expires_at=None,
        etag=None,
        last_modified=None,
        last_content_hash=None,
        notify_email=None,
        interval_minutes=15,
        is_active=True,
        last_checked_at=None,
        last_ok_at=None,
        last_change_detected_at=None,
        last_error_at=None,
        last_email_sent_at=None,
        last_error=None,
    )
    db.add(row)
    db.flush()
    return row
