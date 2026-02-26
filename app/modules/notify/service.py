from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import Change, Input, Notification, NotificationChannel, NotificationStatus
from app.modules.notify.interface import ChangeDigestItem


@dataclass(frozen=True)
class NotificationEnqueueResult:
    dedup_skipped_count: int = 0
    attempted_count: int = 0
    enqueued_count: int = 0
    notification_state: str | None = None


def enqueue_notifications_for_changes(
    db: Session,
    input: Input,
    changes: list[Change],
    *,
    deliver_after: datetime,
    enqueue_reason: str | None = None,
) -> NotificationEnqueueResult:
    del input
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
    before_json = change.before_json or {}
    after_json = change.after_json or {}

    title = str(after_json.get("title") or before_json.get("title") or change.event_uid)
    course_label = str(after_json.get("course_label") or before_json.get("course_label") or "Unknown")
    evidence_path = _read_evidence_path(change)

    return ChangeDigestItem(
        event_uid=change.event_uid,
        change_type=change.change_type.value,
        course_label=course_label,
        title=title,
        before_start_at_utc=_read_timestamp(before_json.get("start_at_utc")),
        after_start_at_utc=_read_timestamp(after_json.get("start_at_utc")),
        delta_seconds=change.delta_seconds,
        detected_at=change.detected_at,
        evidence_path=evidence_path,
    )


def _read_timestamp(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _read_evidence_path(change: Change) -> str | None:
    evidence_keys = change.evidence_keys if isinstance(change.evidence_keys, dict) else None
    if evidence_keys:
        after = evidence_keys.get("after")
        if isinstance(after, dict):
            value = after.get("path")
            if isinstance(value, str) and value:
                return value

    after_snapshot = getattr(change, "after_snapshot", None)
    if after_snapshot and isinstance(after_snapshot.raw_evidence_key, dict):
        value = after_snapshot.raw_evidence_key.get("path")
        if isinstance(value, str) and value:
            return value
    return None


def _build_idempotency_key(change_id: int) -> str:
    return f"email:change:{change_id}"
