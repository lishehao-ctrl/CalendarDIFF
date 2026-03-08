from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, joinedload

from app.core.security import decrypt_secret
from app.db.models.input import InputSource
from app.db.models.notify import Notification, NotificationChannel, NotificationStatus
from app.db.models.review import Change, Input, InputType, ReviewStatus, SourceEventObservation
from app.modules.input_control_plane.provider_sources import CANVAS_ICS_DISPLAY_NAME

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
        item = _serialize_review_change_row(db=db, change=row, input_row=input_row, notification_row=notification_row, now=now)
        proposal_source_ids = _extract_proposal_source_ids(row)
        resolved_source_id = proposal_source_ids[0] if proposal_source_ids else row.input_id
        if source_id is not None and source_id not in {resolved_source_id, *proposal_source_ids}:
            continue
        output.append(item)

    if source_id is not None:
        return output[offset : offset + limit]
    return output


def get_review_change(
    db: Session,
    *,
    user_id: int,
    change_id: int,
) -> dict | None:
    row = db.execute(
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
        .where(Change.id == change_id, Input.user_id == user_id)
        .limit(1)
    ).first()
    if row is None:
        return None
    change_row, input_row, notification_row = row
    return _serialize_review_change_row(
        db=db,
        change=change_row,
        input_row=input_row,
        notification_row=notification_row,
        now=datetime.now(timezone.utc),
    )


def _serialize_review_change_row(
    *,
    db: Session,
    change: Change,
    input_row: Input,
    notification_row: Notification | None,
    now: datetime,
) -> dict:
    sources = _parse_sources(change.proposal_sources_json)
    proposal_source_ids = _extract_proposal_source_ids(change)
    resolved_source_id = proposal_source_ids[0] if proposal_source_ids else change.input_id
    resolved_source_kind = _extract_primary_source_kind(change) or _to_source_kind_value(input_row.type)
    priority_rank = 0 if resolved_source_kind == "email" else 1
    priority_label = "high" if priority_rank == 0 else "normal"
    notification_state, deliver_after = _read_notification_state(notification_row, now=now)
    return {
        "id": change.id,
        "event_uid": change.event_uid,
        "change_type": change.change_type.value,
        "detected_at": change.detected_at,
        "review_status": change.review_status.value,
        "before_json": change.before_json,
        "after_json": change.after_json,
        "proposal_merge_key": change.proposal_merge_key,
        "proposal_sources": sources,
        "source_id": resolved_source_id,
        "viewed_at": change.viewed_at,
        "viewed_note": change.viewed_note,
        "reviewed_at": change.reviewed_at,
        "review_note": change.review_note,
        "source_kind": resolved_source_kind,
        "priority_rank": priority_rank,
        "priority_label": priority_label,
        "notification_state": notification_state,
        "deliver_after": deliver_after,
        "change_summary": _build_change_summary(
            db=db,
            change=change,
            input_row=input_row,
            proposal_sources=sources,
        ),
    }


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


def _build_change_summary(
    *,
    db: Session,
    change: Change,
    input_row: Input,
    proposal_sources: list[dict],
) -> dict:
    before_payload = change.before_json if isinstance(change.before_json, dict) else None
    after_payload = change.after_json if isinstance(change.after_json, dict) else None

    old_source_label = input_row.display_label if before_payload is not None and isinstance(input_row.display_label, str) else None
    old_source_kind = _to_source_kind_value(input_row.type) if before_payload is not None and isinstance(input_row.type, InputType) else None
    old_source_observed_at = change.before_snapshot.retrieved_at if before_payload is not None and change.before_snapshot is not None else None

    new_source_label = None
    new_source_kind = None
    new_source_observed_at = None
    if after_payload is not None:
        primary_source = _extract_primary_proposal_source(proposal_sources)
        if primary_source is None:
            new_source_label = input_row.display_label if isinstance(input_row.display_label, str) else None
            new_source_kind = _to_source_kind_value(input_row.type) if isinstance(input_row.type, InputType) else None
        else:
            source_id = primary_source["source_id"]
            source = db.get(InputSource, source_id)
            new_source_label = _build_source_label(
                source=source,
                provider=primary_source.get("provider"),
                source_kind=primary_source.get("source_kind"),
            )
            new_source_kind = _resolve_source_kind(
                primary_source.get("source_kind"),
                source=source,
            )
            new_source_observed_at = _lookup_source_observed_at(
                db=db,
                change=change,
                source_id=source_id,
                external_event_id=primary_source.get("external_event_id"),
            )

    return {
        "old": {
            "value_time": _extract_value_time(before_payload),
            "source_label": old_source_label,
            "source_kind": old_source_kind,
            "source_observed_at": old_source_observed_at,
        },
        "new": {
            "value_time": _extract_value_time(after_payload),
            "source_label": new_source_label,
            "source_kind": new_source_kind,
            "source_observed_at": new_source_observed_at,
        },
    }


def _extract_primary_proposal_source(proposal_sources: list[dict]) -> dict[str, object] | None:
    for row in proposal_sources:
        source_id = row.get("source_id")
        if isinstance(source_id, int):
            return row
    return None


def _lookup_source_observed_at(
    *,
    db: Session,
    change: Change,
    source_id: int,
    external_event_id: object,
) -> datetime | None:
    if not change.proposal_merge_key:
        return None

    stmt = (
        select(SourceEventObservation.observed_at)
        .where(
            SourceEventObservation.source_id == source_id,
            SourceEventObservation.merge_key == change.proposal_merge_key,
        )
        .order_by(SourceEventObservation.observed_at.desc())
    )
    if isinstance(external_event_id, str) and external_event_id.strip():
        stmt = stmt.where(SourceEventObservation.external_event_id == external_event_id.strip())

    return db.execute(stmt.limit(1)).scalar_one_or_none()


def _build_source_label(*, source: InputSource | None, provider: object, source_kind: object) -> str | None:
    normalized_provider = _normalize_provider(provider)
    if source is not None and source.provider.strip():
        normalized_provider = source.provider.strip().lower()

    if normalized_provider == "ics":
        return CANVAS_ICS_DISPLAY_NAME
    if normalized_provider == "gmail":
        account_email = _extract_gmail_account_email(source)
        return f"Gmail · {account_email}" if account_email else "Gmail"

    if source is not None and isinstance(source.display_name, str) and source.display_name.strip():
        return source.display_name.strip()

    normalized_kind = _resolve_source_kind(source_kind, source=source)
    if normalized_provider:
        return _humanize_token(normalized_provider)
    if normalized_kind:
        return _humanize_token(normalized_kind)
    return None


def _extract_gmail_account_email(source: InputSource | None) -> str | None:
    if source is None or source.secrets is None or not source.secrets.encrypted_payload:
        return None
    try:
        payload = json.loads(decrypt_secret(source.secrets.encrypted_payload))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    account_email = payload.get("account_email")
    if isinstance(account_email, str) and account_email.strip():
        return account_email.strip()
    return None


def _resolve_source_kind(raw_source_kind: object, *, source: InputSource | None) -> str | None:
    if isinstance(raw_source_kind, str):
        normalized = raw_source_kind.strip().lower()
        if normalized in {"calendar", "email"}:
            return normalized
    if source is None:
        return None
    normalized = source.source_kind.value.strip().lower()
    if normalized in {"calendar", "email"}:
        return normalized
    return None


def _normalize_provider(provider: object) -> str | None:
    if not isinstance(provider, str):
        return None
    normalized = provider.strip().lower()
    return normalized or None


def _humanize_token(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").title()


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


__all__ = ["get_review_change", "list_review_changes"]
