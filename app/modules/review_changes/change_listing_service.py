from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, joinedload

from app.db.models.notify import Notification, NotificationChannel, NotificationStatus
from app.db.models.review import Change, Input, InputType, ReviewStatus

SUMMARY_TIME_FIELDS = ("start_at_utc", "internal_date", "due_at", "end_at_utc")


def list_review_changes(
    db: Session,
    *,
    user_id: int,
    review_status: str,
    source_id: int | None,
    limit: int,
    offset: int,
) -> list[dict]:
    stmt = (
        select(Change, Input, Notification)
        .options(joinedload(Change.before_snapshot), joinedload(Change.after_snapshot))
        .join(Input, Input.id == Change.input_id)
        .outerjoin(
            Notification,
            and_(
                Notification.change_id == Change.id,
                Notification.channel == NotificationChannel.EMAIL,
            ),
        )
        .where(Input.user_id == user_id)
    )

    if review_status == "pending":
        stmt = stmt.where(Change.review_status == ReviewStatus.PENDING)
    elif review_status == "approved":
        stmt = stmt.where(Change.review_status == ReviewStatus.APPROVED)
    elif review_status == "rejected":
        stmt = stmt.where(Change.review_status == ReviewStatus.REJECTED)

    db_offset = 0 if source_id is not None else offset
    db_limit = (limit + offset + 512) if source_id is not None else limit
    stmt = stmt.order_by(Change.detected_at.desc(), Change.id.desc()).offset(db_offset).limit(db_limit)
    rows = db.execute(stmt).all()

    now = datetime.now(timezone.utc)
    output: list[dict] = []
    for row, input_row, notification_row in rows:
        sources = _parse_sources(row.proposal_sources_json)
        proposal_source_ids = _extract_proposal_source_ids(row)
        resolved_source_id = proposal_source_ids[0] if proposal_source_ids else row.input_id
        resolved_source_kind = _extract_primary_source_kind(row) or _to_source_kind_value(input_row.type)
        if source_id is not None and source_id not in {resolved_source_id, *proposal_source_ids}:
            continue
        priority_rank = 0 if resolved_source_kind == "email" else 1
        priority_label = "high" if priority_rank == 0 else "normal"
        notification_state, deliver_after = _read_notification_state(notification_row, now=now)
        output.append(
            {
                "id": row.id,
                "event_uid": row.event_uid,
                "change_type": row.change_type.value,
                "detected_at": row.detected_at,
                "review_status": row.review_status.value,
                "before_json": row.before_json,
                "after_json": row.after_json,
                "proposal_merge_key": row.proposal_merge_key,
                "proposal_sources": sources,
                "source_id": resolved_source_id,
                "viewed_at": row.viewed_at,
                "viewed_note": row.viewed_note,
                "reviewed_at": row.reviewed_at,
                "review_note": row.review_note,
                "source_kind": resolved_source_kind,
                "priority_rank": priority_rank,
                "priority_label": priority_label,
                "notification_state": notification_state,
                "deliver_after": deliver_after,
                "change_summary": _build_change_summary(change=row, input_row=input_row),
            }
        )

    if source_id is not None:
        return output[offset : offset + limit]
    return output


def _parse_sources(raw_sources: object) -> list[dict]:
    if not isinstance(raw_sources, list):
        return []
    out: list[dict] = []
    for item in raw_sources:
        if not isinstance(item, dict):
            continue
        source_id = item.get("source_id")
        if not isinstance(source_id, int):
            continue
        source_kind = item.get("source_kind") if isinstance(item.get("source_kind"), str) else None
        provider = item.get("provider") if isinstance(item.get("provider"), str) else None
        external_event_id = item.get("external_event_id") if isinstance(item.get("external_event_id"), str) else None
        confidence_raw = item.get("confidence")
        confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else None
        out.append(
            {
                "source_id": source_id,
                "source_kind": source_kind,
                "provider": provider,
                "external_event_id": external_event_id,
                "confidence": confidence,
            }
        )
    return out


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


def _build_change_summary(*, change: Change, input_row: Input) -> dict:
    source_label = input_row.display_label if isinstance(input_row.display_label, str) else None
    source_kind = _to_source_kind_value(input_row.type) if isinstance(input_row.type, InputType) else None

    before_payload = change.before_json if isinstance(change.before_json, dict) else None
    after_payload = change.after_json if isinstance(change.after_json, dict) else None

    return {
        "old": {
            "value_time": _extract_value_time(before_payload),
            "source_label": source_label,
            "source_kind": source_kind,
            "source_observed_at": change.before_snapshot.retrieved_at if change.before_snapshot is not None else None,
        },
        "new": {
            "value_time": _extract_value_time(after_payload),
            "source_label": source_label,
            "source_kind": source_kind,
            "source_observed_at": change.after_snapshot.retrieved_at if change.after_snapshot is not None else None,
        },
    }


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


__all__ = ["list_review_changes"]
