from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import require_api_key
from app.db.session import get_db
from app.modules.notify.digest_service import send_digest_for_slot
from app.modules.notify.prefs_schemas import NotificationPrefsResponse, NotificationPrefsUpdateRequest
from app.modules.notify.prefs_service import get_or_create_notification_prefs, update_notification_prefs
from app.modules.users.service import UserNotInitializedError, require_initialized_user, user_not_initialized_detail

router = APIRouter(prefix="/v1", tags=["notifications"], dependencies=[Depends(require_api_key)])


@router.get("/notification_prefs", response_model=NotificationPrefsResponse)
def get_notification_prefs(db: Session = Depends(get_db)) -> NotificationPrefsResponse:
    try:
        user = require_initialized_user(db)
    except UserNotInitializedError as exc:
        raise HTTPException(status_code=409, detail=user_not_initialized_detail()) from exc
    prefs = get_or_create_notification_prefs(db, user_id=user.id)
    return NotificationPrefsResponse(
        digest_enabled=prefs.digest_enabled,
        timezone=prefs.timezone,
        digest_times=[item for item in prefs.digest_times if isinstance(item, str)],
    )


@router.put("/notification_prefs", response_model=NotificationPrefsResponse)
def put_notification_prefs(payload: NotificationPrefsUpdateRequest, db: Session = Depends(get_db)) -> NotificationPrefsResponse:
    try:
        user = require_initialized_user(db)
    except UserNotInitializedError as exc:
        raise HTTPException(status_code=409, detail=user_not_initialized_detail()) from exc
    prefs = get_or_create_notification_prefs(db, user_id=user.id)
    try:
        updated = update_notification_prefs(
            db,
            row=prefs,
            digest_enabled=payload.digest_enabled,
            timezone=payload.timezone,
            digest_times=payload.digest_times,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return NotificationPrefsResponse(
        digest_enabled=updated.digest_enabled,
        timezone=updated.timezone,
        digest_times=[item for item in updated.digest_times if isinstance(item, str)],
    )


@router.post("/notifications/send_digest_now")
def post_send_digest_now(db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        user = require_initialized_user(db)
    except UserNotInitializedError as exc:
        raise HTTPException(status_code=409, detail=user_not_initialized_detail()) from exc
    prefs = get_or_create_notification_prefs(db, user_id=user.id)

    current = datetime.now(timezone.utc)
    try:
        tz_now = current.astimezone(ZoneInfo(prefs.timezone))
    except Exception:  # pragma: no cover - platform tzdata variation
        tz_now = current.astimezone(timezone.utc)
    local_date = tz_now.date()
    local_time = tz_now.strftime("%H:%M")

    send_digest_for_slot(
        db,
        user=user,
        scheduled_local_date=local_date,
        scheduled_local_time=local_time,
        now=current,
    )
    return {
        "status": "ok",
        "scheduled_local_date": local_date.isoformat(),
        "scheduled_local_time": local_time,
    }
