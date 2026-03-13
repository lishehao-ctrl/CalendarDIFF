from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models.notify import Notification, NotificationChannel, NotificationStatus
from app.db.models.review import Change
from app.modules.common.event_display import event_display_from_payload
from app.modules.core_ingest.semantic_event_service import normalize_time_precision, semantic_due_datetime_from_payload
from app.modules.notify.interface import ChangeDigestItem


@dataclass(frozen=True)
class NotificationEnqueueResult:
    dedup_skipped_count: int = 0
    attempted_count: int = 0
    enqueued_count: int = 0
    notification_state: str | None = None


def enqueue_notifications_for_changes(
    db: Session,
    changes: list[Change],
    *,
    deliver_after: datetime,
    enqueue_reason: str | None = None,
) -> NotificationEnqueueResult:
    if not changes:
        return NotificationEnqueueResult()

    change_by_id = {change.id: change for change in changes if change.id is not None}
    if not change_by_id:
        return NotificationEnqueueResult()

    existing_rows = db.scalars(
        select(Notification).where(
            Notification.change_id.in_(change_by_id),
            Notification.channel == NotificationChannel.EMAIL,
        )
    ).all()
    existing_change_ids = {row.change_id for row in existing_rows}

    dedup_skipped_count = 0
    inserted_ids: list[int] = []
    for change_id in change_by_id:
        if change_id in existing_change_ids:
            dedup_skipped_count += 1
            continue

        insert_stmt = (
            pg_insert(Notification)
            .values(
                change_id=change_id,
                channel=NotificationChannel.EMAIL,
                status=NotificationStatus.PENDING,
                sent_at=None,
                error=None,
                idempotency_key=_build_idempotency_key(change_id),
                deliver_after=deliver_after,
                enqueue_reason=enqueue_reason,
            )
            .on_conflict_do_nothing()
            .returning(Notification.id)
        )
        inserted_id = db.execute(insert_stmt).scalar_one_or_none()
        if inserted_id is None:
            dedup_skipped_count += 1
            continue
        inserted_ids.append(inserted_id)

    return NotificationEnqueueResult(
        dedup_skipped_count=dedup_skipped_count,
        attempted_count=len(inserted_ids),
        enqueued_count=len(inserted_ids),
        notification_state="queued" if inserted_ids else None,
    )


def _to_digest_item(change: Change) -> ChangeDigestItem:
    before_payload = change.before_semantic_json if isinstance(change.before_semantic_json, dict) else {}
    after_payload = change.after_semantic_json if isinstance(change.after_semantic_json, dict) else {}
    evidence_path = _read_evidence_path(change)

    return ChangeDigestItem(
        entity_uid=change.entity_uid,
        change_type=change.change_type.value,
        before_display=event_display_from_payload(before_payload, strict=True) if before_payload else None,
        after_display=event_display_from_payload(after_payload, strict=True) if after_payload else None,
        before_due_at=_read_semantic_due(before_payload),
        after_due_at=_read_semantic_due(after_payload),
        before_time_precision=_read_time_precision(before_payload),
        after_time_precision=_read_time_precision(after_payload),
        delta_seconds=change.delta_seconds,
        detected_at=change.detected_at,
        evidence_path=evidence_path,
    )


def _read_semantic_due(payload: dict[str, object]) -> str | None:
    due_at = semantic_due_datetime_from_payload(payload)
    return due_at.isoformat() if due_at is not None else None


def _read_time_precision(payload: dict[str, object]) -> str:
    try:
        return normalize_time_precision(payload.get("time_precision"))
    except Exception:
        return "datetime"


def _read_evidence_path(change: Change) -> str | None:
    return None


def _build_idempotency_key(change_id: int) -> str:
    return f"email:change:{change_id}"
