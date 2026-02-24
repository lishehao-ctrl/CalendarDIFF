from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    Change,
    Notification,
    NotificationChannel,
    NotificationStatus,
    Input,
    InputType,
)
from app.modules.notify.email import SMTPEmailNotifier
from app.modules.notify.interface import ChangeDigestItem, Notifier


@dataclass(frozen=True)
class NotificationDispatchResult:
    email_sent: bool
    error: str | None
    dedup_skipped_count: int = 0
    attempted_count: int = 0
    enqueued_count: int = 0
    notification_state: str | None = None


@dataclass(frozen=True)
class DueDispatchResult:
    attempted_source_count: int
    sent_source_count: int
    failed_by_source_id: dict[int, str]


def enqueue_notifications_for_changes(
    db: Session,
    input: Input,
    changes: list[Change],
    *,
    deliver_after: datetime,
    enqueue_reason: str | None = None,
) -> NotificationDispatchResult:
    if not changes:
        return NotificationDispatchResult(
            email_sent=False,
            error=None,
            dedup_skipped_count=0,
            attempted_count=0,
            enqueued_count=0,
            notification_state=None,
        )

    change_by_id = {change.id: change for change in changes if change.id is not None}
    if not change_by_id:
        return NotificationDispatchResult(
            email_sent=False,
            error=None,
            dedup_skipped_count=0,
            attempted_count=0,
            enqueued_count=0,
            notification_state=None,
        )

    stmt = select(Notification).where(
        Notification.change_id.in_(change_by_id),
        Notification.channel == NotificationChannel.EMAIL,
    )
    existing_rows = db.scalars(stmt).all()
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
            .on_conflict_do_nothing(constraint="uq_notifications_change_channel")
            .returning(Notification.id)
        )
        inserted_id = db.execute(insert_stmt).scalar_one_or_none()
        if inserted_id is None:
            dedup_skipped_count += 1
            continue
        inserted_ids.append(inserted_id)

    return NotificationDispatchResult(
        email_sent=False,
        error=None,
        dedup_skipped_count=dedup_skipped_count,
        attempted_count=len(inserted_ids),
        enqueued_count=len(inserted_ids),
        notification_state="queued" if inserted_ids else None,
    )


def dispatch_due_notifications(
    db: Session,
    *,
    now: datetime | None = None,
    input_id: int | None = None,
    notifier: Notifier | None = None,
) -> DueDispatchResult:
    current = now or datetime.now(timezone.utc)
    priority_rank_expr = (Input.type == InputType.EMAIL).desc()

    stmt = (
        select(Notification, Change, Input)
        .join(Change, Notification.change_id == Change.id)
        .join(Input, Change.input_id == Input.id)
        .where(
            Notification.channel == NotificationChannel.EMAIL,
            Notification.status == NotificationStatus.PENDING,
            Notification.deliver_after <= current,
            or_(Notification.enqueue_reason.is_(None), Notification.enqueue_reason != "digest_queue"),
        )
        .order_by(
            Input.user_id.asc(),
            priority_rank_expr,
            Notification.deliver_after.asc(),
            Change.detected_at.asc(),
            Notification.id.asc(),
        )
    )
    if input_id is not None:
        stmt = stmt.where(Input.id == input_id)

    rows = db.execute(stmt).all()
    if not rows:
        return DueDispatchResult(attempted_source_count=0, sent_source_count=0, failed_by_source_id={})

    grouped: OrderedDict[int, list[tuple[Notification, Change, Input]]] = OrderedDict()
    for notification, change, input in rows:
        grouped.setdefault(input.id, []).append((notification, change, input))

    notifier_impl = notifier or SMTPEmailNotifier()
    failed_by_source_id: dict[int, str] = {}
    sent_source_count = 0

    for current_source_id, source_rows in grouped.items():
        input = source_rows[0][2]
        user_notify_email = input.user.notify_email if input.user is not None else None
        user_email = input.user.email if input.user is not None else None
        to_email = user_notify_email or user_email or get_settings().default_notify_email
        notifications = [item[0] for item in source_rows]
        changes = [item[1] for item in source_rows]

        if not to_email:
            error_message = "No notification recipient configured"
            for notification in notifications:
                notification.status = NotificationStatus.FAILED
                notification.error = error_message
                notification.sent_at = None
            failed_by_source_id[current_source_id] = error_message
            continue

        digest_items = [_to_digest_item(change) for change in changes]
        send_result = notifier_impl.send_changes_digest(
            to_email,
            input.display_label,
            input.id,
            digest_items,
        )
        if send_result.success:
            sent_source_count += 1
            sent_at = datetime.now(timezone.utc)
            for notification in notifications:
                notification.status = NotificationStatus.SENT
                notification.error = None
                notification.sent_at = sent_at
        else:
            error_message = send_result.error or "unknown send failure"
            failed_by_source_id[current_source_id] = error_message
            for notification in notifications:
                notification.status = NotificationStatus.FAILED
                notification.error = error_message
                notification.sent_at = None

    return DueDispatchResult(
        attempted_source_count=len(grouped),
        sent_source_count=sent_source_count,
        failed_by_source_id=failed_by_source_id,
    )


def dispatch_notifications_for_changes(
    db: Session,
    input: Input,
    changes: list[Change],
    notifier: Notifier | None = None,
) -> NotificationDispatchResult:
    now = datetime.now(timezone.utc)
    enqueue_result = enqueue_notifications_for_changes(
        db,
        input,
        changes,
        deliver_after=now,
        enqueue_reason=None,
    )
    if enqueue_result.attempted_count == 0:
        return NotificationDispatchResult(
            email_sent=False,
            error=None,
            dedup_skipped_count=enqueue_result.dedup_skipped_count,
            attempted_count=0,
            enqueued_count=0,
            notification_state=None,
        )

    due_result = dispatch_due_notifications(
        db,
        now=now,
        input_id=input.id,
        notifier=notifier,
    )
    source_error = due_result.failed_by_source_id.get(input.id)
    source_sent = input.id not in due_result.failed_by_source_id and due_result.sent_source_count > 0
    return NotificationDispatchResult(
        email_sent=source_sent,
        error=source_error,
        dedup_skipped_count=enqueue_result.dedup_skipped_count,
        attempted_count=enqueue_result.attempted_count,
        enqueued_count=enqueue_result.enqueued_count,
        notification_state="sent" if source_sent else ("failed" if source_error else "queued"),
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
