from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.security import require_api_key
from app.db.models import (
    Change,
    Input,
    InputType,
    Notification,
    NotificationChannel,
    NotificationStatus,
)
from app.db.session import get_db
from app.modules.changes.schemas import ChangeFeedResponse, ChangeResponse, ChangeSummary, ChangeSummarySide
from app.modules.users.service import (
    UserNotInitializedError,
    UserOnboardingIncompleteError,
    require_onboarded_user,
    user_onboarding_incomplete_detail,
    user_not_initialized_detail,
)

router = APIRouter(prefix="/v1", tags=["changes"], dependencies=[Depends(require_api_key)])
SUMMARY_TIME_FIELDS = ("start_at_utc", "internal_date", "due_at", "end_at_utc")


@router.get("/feed", response_model=list[ChangeFeedResponse])
def list_feed(
    input_id: int | None = Query(default=None),
    view: str = Query(default="all"),
    input_types: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[ChangeFeedResponse]:
    settings = get_settings()
    applied_limit = limit or settings.default_changes_limit
    applied_limit = min(applied_limit, settings.max_changes_limit)

    requested_types = _parse_input_types(input_types)

    try:
        current_user_id = require_onboarded_user(db).id
    except UserNotInitializedError as exc:
        raise HTTPException(status_code=409, detail=user_not_initialized_detail()) from exc
    except UserOnboardingIncompleteError as exc:
        raise HTTPException(status_code=409, detail=user_onboarding_incomplete_detail()) from exc

    priority_rank_expr = case((Input.type == InputType.EMAIL, 0), else_=1)

    stmt = (
        select(Change, Input, Notification)
        .options(joinedload(Change.before_snapshot), joinedload(Change.after_snapshot))
        .join(Input, Change.input_id == Input.id)
        .outerjoin(
            Notification,
            and_(
                Notification.change_id == Change.id,
                Notification.channel == NotificationChannel.EMAIL,
            ),
        )
    )

    if input_id is not None:
        stmt = stmt.where(Change.input_id == input_id)
    stmt = stmt.where(Input.user_id == current_user_id)
    if requested_types is not None:
        stmt = stmt.where(Input.type.in_(requested_types))
    if view == "unread":
        stmt = stmt.where(Change.viewed_at.is_(None))

    stmt = stmt.order_by(priority_rank_expr.asc(), Change.detected_at.desc(), Change.id.desc()).offset(offset).limit(applied_limit)
    rows = db.execute(stmt).all()

    now = datetime.now(timezone.utc)
    result: list[ChangeFeedResponse] = []
    for change, input, notification in rows:
        base = _to_response(change)
        priority_rank = 0 if input.type == InputType.EMAIL else 1
        priority_label = "high" if priority_rank == 0 else "normal"
        notification_state, deliver_after = _read_notification_state(notification, now=now)
        result.append(
            ChangeFeedResponse(
                **base.model_dump(),
                input_type=input.type.value,
                priority_rank=priority_rank,
                priority_label=priority_label,
                notification_state=notification_state,
                deliver_after=deliver_after,
                change_summary=_build_change_summary(change=change, input_row=input),
            )
        )
    return result


def _to_response(row: Change) -> ChangeResponse:
    return ChangeResponse(
        id=row.id,
        input_id=row.input_id,
        event_uid=row.event_uid,
        change_type=row.change_type.value,
        detected_at=row.detected_at,
        before_json=row.before_json,
        after_json=row.after_json,
        delta_seconds=row.delta_seconds,
        before_snapshot_id=row.before_snapshot_id,
        after_snapshot_id=row.after_snapshot_id,
        evidence_keys=row.evidence_keys,
        before_raw_evidence_key=row.before_snapshot.raw_evidence_key if row.before_snapshot else None,
        after_raw_evidence_key=row.after_snapshot.raw_evidence_key if row.after_snapshot else None,
        viewed_at=row.viewed_at,
        viewed_note=row.viewed_note,
    )


def _parse_input_types(raw_value: str | None) -> list[InputType] | None:
    if raw_value is None or not raw_value.strip():
        return None
    parsed: list[InputType] = []
    for item in raw_value.split(","):
        value = item.strip().lower()
        if not value:
            continue
        if value == InputType.EMAIL.value:
            parsed.append(InputType.EMAIL)
        elif value == InputType.ICS.value:
            parsed.append(InputType.ICS)
    return parsed or None


def _read_notification_state(
    row: Notification | None,
    *,
    now: datetime,
) -> tuple[str | None, datetime | None]:
    if row is None:
        return None, None

    deliver_after = row.deliver_after
    if row.status == NotificationStatus.PENDING:
        if deliver_after > now and row.enqueue_reason == "email_priority_delay":
            return "queued_delayed_by_email_priority", deliver_after
        if deliver_after > now:
            return "queued_delayed", deliver_after
        return "queued", deliver_after
    if row.status == NotificationStatus.SENT:
        return "sent", deliver_after
    if row.status == NotificationStatus.FAILED:
        return "failed", deliver_after
    return None, deliver_after


def _build_change_summary(*, change: Change, input_row: Input) -> ChangeSummary:
    source_label = input_row.display_label if isinstance(input_row.display_label, str) else None
    source_type = input_row.type.value if isinstance(input_row.type, InputType) else None

    before_payload = change.before_json if isinstance(change.before_json, dict) else None
    after_payload = change.after_json if isinstance(change.after_json, dict) else None

    return ChangeSummary(
        old=ChangeSummarySide(
            value_time=_extract_value_time(before_payload),
            source_label=source_label,
            source_type=source_type,
            source_observed_at=change.before_snapshot.retrieved_at if change.before_snapshot is not None else None,
        ),
        new=ChangeSummarySide(
            value_time=_extract_value_time(after_payload),
            source_label=source_label,
            source_type=source_type,
            source_observed_at=change.after_snapshot.retrieved_at if change.after_snapshot is not None else None,
        ),
    )


def _extract_value_time(payload: dict[str, Any] | None) -> datetime | None:
    if payload is None:
        return None
    for key in SUMMARY_TIME_FIELDS:
        parsed = _coerce_datetime(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
