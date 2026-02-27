from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from icalendar import Calendar
from sqlalchemy import and_, case, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.logging import sanitize_log_message
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
from app.modules.common.deps import get_onboarded_user_or_409
from app.modules.changes.schemas import (
    ChangeFeedResponse,
    ChangeViewedUpdateRequest,
    ChangeResponse,
    ChangeSummary,
    ChangeSummarySide,
    EvidencePreviewEvent,
    EvidencePreviewResponse,
)
from app.modules.evidence import EvidencePathError, resolve_evidence_file_path

router = APIRouter(prefix="/v1", tags=["changes"], dependencies=[Depends(require_api_key)])
SUMMARY_TIME_FIELDS = ("start_at_utc", "internal_date", "due_at", "end_at_utc")
PREVIEW_MAX_BYTES = 64 * 1024
PREVIEW_DESCRIPTION_MAX_CHARS = 240
logger = logging.getLogger(__name__)


@router.get("/feed", response_model=list[ChangeFeedResponse])
def list_feed(
    input_id: int | None = Query(default=None),
    view: str = Query(default="all"),
    input_types: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> list[ChangeFeedResponse]:
    settings = get_settings()
    applied_limit = limit or settings.default_changes_limit
    applied_limit = min(applied_limit, settings.max_changes_limit)

    requested_types = _parse_input_types(input_types)

    current_user_id = user.id

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


@router.patch("/changes/{change_id}/viewed", response_model=ChangeResponse)
def mark_change_viewed(
    change_id: int,
    payload: ChangeViewedUpdateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ChangeResponse:
    row = db.scalar(
        select(Change)
        .join(Input, Input.id == Change.input_id)
        .options(joinedload(Change.before_snapshot), joinedload(Change.after_snapshot))
        .where(Change.id == change_id, Input.user_id == user.id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Change not found")

    if payload.viewed:
        row.viewed_at = datetime.now(timezone.utc)
        row.viewed_note = payload.note
    else:
        row.viewed_at = None
        row.viewed_note = None

    db.commit()
    db.refresh(row)
    return _to_response(row)


@router.get("/changes/{change_id}/evidence/{side}/preview", response_model=EvidencePreviewResponse)
def preview_change_evidence(
    change_id: int,
    side: Literal["before", "after"],
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> EvidencePreviewResponse:
    row, resolved = _resolve_change_evidence_file(db, user_id=user.id, change_id=change_id, side=side)
    try:
        content_bytes = resolved.read_bytes()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Evidence file not found") from None
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.error("failed to read evidence preview error=%s", sanitize_log_message(str(exc)))
        raise HTTPException(status_code=500, detail="Failed to prepare evidence preview")

    truncated = len(content_bytes) > PREVIEW_MAX_BYTES
    try:
        events = _build_evidence_preview_events(content_bytes)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "evidence_parse_failed",
                "message": "Failed to parse ICS evidence preview",
            },
        ) from exc
    return EvidencePreviewResponse(
        side=side,
        content_type="text/calendar",
        truncated=truncated,
        filename=f"change-{row.id}-{side}.ics",
        event_count=len(events),
        events=events,
    )


def _to_response(row: Change) -> ChangeResponse:
    before_evidence = _extract_snapshot_evidence_key(row.before_snapshot.raw_evidence_key if row.before_snapshot else None)
    after_evidence = _extract_snapshot_evidence_key(row.after_snapshot.raw_evidence_key if row.after_snapshot else None)
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
        has_before_evidence=before_evidence is not None,
        has_after_evidence=after_evidence is not None,
        before_evidence_kind=_extract_evidence_kind(before_evidence),
        after_evidence_kind=_extract_evidence_kind(after_evidence),
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
    input_label = input_row.display_label if isinstance(input_row.display_label, str) else None
    input_type = input_row.type.value if isinstance(input_row.type, InputType) else None

    before_payload = change.before_json if isinstance(change.before_json, dict) else None
    after_payload = change.after_json if isinstance(change.after_json, dict) else None

    return ChangeSummary(
        old=ChangeSummarySide(
            value_time=_extract_value_time(before_payload),
            input_label=input_label,
            input_type=input_type,
            input_observed_at=change.before_snapshot.retrieved_at if change.before_snapshot is not None else None,
        ),
        new=ChangeSummarySide(
            value_time=_extract_value_time(after_payload),
            input_label=input_label,
            input_type=input_type,
            input_observed_at=change.after_snapshot.retrieved_at if change.after_snapshot is not None else None,
        ),
    )


def _extract_snapshot_evidence_key(raw_evidence_key: object) -> dict[str, Any] | None:
    if not isinstance(raw_evidence_key, dict):
        return None
    return raw_evidence_key


def _extract_snapshot_evidence_path(raw_evidence_key: object) -> str | None:
    key = _extract_snapshot_evidence_key(raw_evidence_key)
    if key is None:
        return None
    path_value = key.get("path")
    if isinstance(path_value, str) and path_value:
        return path_value
    return None


def _extract_evidence_kind(raw_evidence_key: dict[str, Any] | None) -> str | None:
    if raw_evidence_key is None:
        return None
    kind = raw_evidence_key.get("kind")
    if isinstance(kind, str) and kind.strip():
        return kind.strip()
    return None


def _resolve_change_evidence_file(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    side: Literal["before", "after"],
) -> tuple[Change, Path]:
    row = db.scalar(
        select(Change)
        .join(Input, Input.id == Change.input_id)
        .options(joinedload(Change.before_snapshot), joinedload(Change.after_snapshot))
        .where(Change.id == change_id, Input.user_id == user_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Change not found")

    snapshot = row.before_snapshot if side == "before" else row.after_snapshot
    evidence_path = _extract_snapshot_evidence_path(snapshot.raw_evidence_key if snapshot is not None else None)
    if evidence_path is None:
        raise HTTPException(status_code=404, detail="Evidence file not found")

    try:
        resolved = resolve_evidence_file_path(evidence_path)
    except EvidencePathError:
        raise HTTPException(status_code=404, detail="Evidence file not found") from None
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.error("failed to resolve evidence path error=%s", sanitize_log_message(str(exc)))
        raise HTTPException(status_code=500, detail="Failed to prepare evidence file")

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Evidence file not found")
    return row, resolved


def _build_evidence_preview_events(content_bytes: bytes) -> list[EvidencePreviewEvent]:
    try:
        calendar = Calendar.from_ical(content_bytes)
    except Exception as exc:
        raise ValueError("failed to parse ICS evidence") from exc

    events: list[EvidencePreviewEvent] = []
    for component in calendar.walk("VEVENT"):
        description = _to_preview_text(component.get("description"), prefer_ical=False)
        if description and len(description) > PREVIEW_DESCRIPTION_MAX_CHARS:
            description = f"{description[:PREVIEW_DESCRIPTION_MAX_CHARS].rstrip()}..."

        events.append(
            EvidencePreviewEvent(
                uid=_to_preview_text(component.get("uid"), prefer_ical=False),
                summary=_to_preview_text(component.get("summary"), prefer_ical=False),
                dtstart=_to_preview_text(component.get("dtstart"), prefer_ical=True),
                dtend=_to_preview_text(component.get("dtend"), prefer_ical=True),
                location=_to_preview_text(component.get("location"), prefer_ical=False),
                description=description,
            )
        )
    return events


def _to_preview_text(value: object, *, prefer_ical: bool) -> str | None:
    if value is None:
        return None

    if prefer_ical and hasattr(value, "to_ical"):
        try:
            encoded = value.to_ical()
            if isinstance(encoded, bytes):
                text = encoded.decode("utf-8", errors="replace").strip()
            else:
                text = str(encoded).strip()
            if text:
                return text
        except Exception:  # pragma: no cover - fallback below
            pass

    text = str(value).strip()
    return text or None


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
