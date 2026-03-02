from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
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
    ReviewStatus,
)
from app.db.session import get_db
from app.modules.common.deps import get_onboarded_user_or_409
from app.modules.changes.schemas import (
    ChangeFeedResponse,
    ChangeViewedUpdateRequest,
    ChangeResponse,
    ChangeSummary,
    ChangeSummarySide,
    EvidencePreviewResponse,
)
from app.modules.evidence import EvidencePathError, resolve_evidence_file_path

router = APIRouter(prefix="/v2", tags=["change-events"], dependencies=[Depends(require_api_key)])
SUMMARY_TIME_FIELDS = ("start_at_utc", "internal_date", "due_at", "end_at_utc")
PREVIEW_MAX_BYTES = 64 * 1024
logger = logging.getLogger(__name__)


@router.get("/change-events", response_model=list[ChangeFeedResponse])
def list_feed(
    source_id: int | None = Query(default=None),
    view: str = Query(default="all"),
    review_status: Literal["approved", "pending", "rejected", "all"] = Query(default="approved"),
    source_kinds: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> list[ChangeFeedResponse]:
    settings = get_settings()
    applied_limit = limit or settings.default_changes_limit
    applied_limit = min(applied_limit, settings.max_changes_limit)

    requested_types = _parse_source_kinds(source_kinds)

    current_user_id = user.id

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

    stmt = stmt.where(Input.user_id == current_user_id)
    if review_status == "approved":
        stmt = stmt.where(Change.review_status == ReviewStatus.APPROVED)
    elif review_status == "pending":
        stmt = stmt.where(Change.review_status == ReviewStatus.PENDING)
    elif review_status == "rejected":
        stmt = stmt.where(Change.review_status == ReviewStatus.REJECTED)
    if requested_types is not None:
        stmt = stmt.where(Input.type.in_(requested_types))
    if view == "unread":
        stmt = stmt.where(Change.viewed_at.is_(None))

    db_offset = 0 if source_id is not None else offset
    db_limit = (applied_limit + offset + 512) if source_id is not None else applied_limit
    stmt = stmt.order_by(Change.detected_at.desc(), Change.id.desc()).offset(db_offset).limit(db_limit)
    rows = db.execute(stmt).all()

    now = datetime.now(timezone.utc)
    result: list[ChangeFeedResponse] = []
    for change, input, notification in rows:
        proposal_source_ids = _extract_proposal_source_ids(change)
        resolved_source_id = proposal_source_ids[0] if proposal_source_ids else change.input_id
        resolved_source_kind = _extract_primary_source_kind(change) or _to_source_kind_value(input.type)
        if source_id is not None and source_id not in {resolved_source_id, *proposal_source_ids}:
            continue
        base = _to_response(change, source_id=resolved_source_id)
        priority_rank = 0 if resolved_source_kind == "email" else 1
        priority_label = "high" if priority_rank == 0 else "normal"
        notification_state, deliver_after = _read_notification_state(notification, now=now)
        result.append(
            ChangeFeedResponse(
                **base.model_dump(),
                source_kind=resolved_source_kind,
                priority_rank=priority_rank,
                priority_label=priority_label,
                notification_state=notification_state,
                deliver_after=deliver_after,
                change_summary=_build_change_summary(change=change, input_row=input),
            )
        )
    if source_id is not None:
        return result[offset : offset + applied_limit]
    return result


@router.patch("/change-events/{change_id}", response_model=ChangeResponse)
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
    proposal_source_ids = _extract_proposal_source_ids(row)
    resolved_source_id = proposal_source_ids[0] if proposal_source_ids else row.input_id
    return _to_response(row, source_id=resolved_source_id)


@router.get("/change-events/{change_id}/evidence/{side}/preview", response_model=EvidencePreviewResponse)
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
    preview_text = _build_evidence_preview_text(content_bytes)
    return EvidencePreviewResponse(
        side=side,
        content_type="text/calendar",
        truncated=truncated,
        filename=f"change-{row.id}-{side}.ics",
        event_count=0,
        events=[],
        preview_text=preview_text,
    )


def _to_response(row: Change, *, source_id: int | None = None) -> ChangeResponse:
    before_evidence = _extract_snapshot_evidence_key(row.before_snapshot.raw_evidence_key if row.before_snapshot else None)
    after_evidence = _extract_snapshot_evidence_key(row.after_snapshot.raw_evidence_key if row.after_snapshot else None)
    return ChangeResponse(
        id=row.id,
        source_id=source_id or row.input_id,
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


def _parse_source_kinds(raw_value: str | None) -> list[InputType] | None:
    if raw_value is None or not raw_value.strip():
        return None
    parsed: list[InputType] = []
    for item in raw_value.split(","):
        value = item.strip().lower()
        if not value:
            continue
        if value in {InputType.EMAIL.value, "email"}:
            parsed.append(InputType.EMAIL)
        elif value in {InputType.ICS.value, "calendar"}:
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
    source_kind = _to_source_kind_value(input_row.type) if isinstance(input_row.type, InputType) else None

    before_payload = change.before_json if isinstance(change.before_json, dict) else None
    after_payload = change.after_json if isinstance(change.after_json, dict) else None

    return ChangeSummary(
        old=ChangeSummarySide(
            value_time=_extract_value_time(before_payload),
            source_label=source_label,
            source_kind=source_kind,
            source_observed_at=change.before_snapshot.retrieved_at if change.before_snapshot is not None else None,
        ),
        new=ChangeSummarySide(
            value_time=_extract_value_time(after_payload),
            source_label=source_label,
            source_kind=source_kind,
            source_observed_at=change.after_snapshot.retrieved_at if change.after_snapshot is not None else None,
        ),
    )


def _to_source_kind_value(input_type: InputType) -> str:
    if input_type == InputType.ICS:
        return "calendar"
    return "email"


def _extract_proposal_source_ids(change: Change) -> list[int]:
    sources = change.proposal_sources_json if isinstance(change.proposal_sources_json, list) else []
    out: list[int] = []
    for row in sources:
        if not isinstance(row, dict):
            continue
        source_id = row.get("source_id")
        if isinstance(source_id, int):
            out.append(source_id)
    return out


def _extract_primary_source_kind(change: Change) -> str | None:
    sources = change.proposal_sources_json if isinstance(change.proposal_sources_json, list) else []
    for row in sources:
        if not isinstance(row, dict):
            continue
        source_kind = row.get("source_kind")
        if isinstance(source_kind, str):
            normalized = source_kind.strip().lower()
            if normalized in {"calendar", "email"}:
                return normalized
    return None


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


def _build_evidence_preview_text(content_bytes: bytes) -> str:
    preview_bytes = content_bytes[:PREVIEW_MAX_BYTES]
    return preview_bytes.decode("utf-8", errors="replace")


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
