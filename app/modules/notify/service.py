from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Change, Notification, NotificationChannel, NotificationStatus, Source
from app.modules.notify.email import SMTPEmailNotifier
from app.modules.notify.interface import ChangeDigestItem, Notifier


@dataclass(frozen=True)
class NotificationDispatchResult:
    email_sent: bool
    error: str | None


def dispatch_notifications_for_changes(
    db: Session,
    source: Source,
    changes: list[Change],
    notifier: Notifier | None = None,
) -> NotificationDispatchResult:
    if not changes:
        return NotificationDispatchResult(email_sent=False, error=None)

    change_by_id = {change.id: change for change in changes if change.id is not None}
    if not change_by_id:
        return NotificationDispatchResult(email_sent=False, error=None)

    stmt = select(Notification).where(
        Notification.change_id.in_(change_by_id),
        Notification.channel == NotificationChannel.EMAIL,
    ).order_by(Notification.id.desc())
    existing_rows = db.scalars(stmt).all()
    existing_by_change_id: dict[int, Notification] = {}
    for row in existing_rows:
        if row.change_id not in existing_by_change_id:
            existing_by_change_id[row.change_id] = row

    pending_notifications: list[Notification] = []
    changes_to_send: list[Change] = []
    for change_id, change in change_by_id.items():
        existing = existing_by_change_id.get(change_id)
        if existing and existing.status in {NotificationStatus.SENT, NotificationStatus.PENDING}:
            continue

        if existing and existing.status == NotificationStatus.FAILED:
            existing.status = NotificationStatus.PENDING
            existing.sent_at = None
            existing.error = None
            if not existing.idempotency_key:
                existing.idempotency_key = _build_idempotency_key(change_id)
            pending_notifications.append(existing)
            changes_to_send.append(change)
            continue

        notification = Notification(
            change_id=change_id,
            channel=NotificationChannel.EMAIL,
            status=NotificationStatus.PENDING,
            sent_at=None,
            error=None,
            idempotency_key=_build_idempotency_key(change_id),
        )
        db.add(notification)
        pending_notifications.append(notification)
        changes_to_send.append(change)

    if not pending_notifications:
        return NotificationDispatchResult(email_sent=False, error=None)

    db.flush()

    settings = get_settings()
    to_email = settings.default_notify_email or (source.user.email if source.user else None)
    if not to_email:
        for notification in pending_notifications:
            notification.status = NotificationStatus.FAILED
            notification.error = "No notification recipient configured"
        return NotificationDispatchResult(email_sent=False, error="No notification recipient configured")

    notifier_impl = notifier or SMTPEmailNotifier()
    digest_items = [_to_digest_item(change) for change in changes_to_send]
    send_result = notifier_impl.send_changes_digest(
        to_email=to_email,
        source_name=source.name or f"source-{source.id}",
        source_id=source.id,
        items=digest_items,
    )

    now = datetime.now(timezone.utc)
    if send_result.success:
        for notification in pending_notifications:
            notification.status = NotificationStatus.SENT
            notification.sent_at = now
            notification.error = None
        return NotificationDispatchResult(email_sent=True, error=None)

    for notification in pending_notifications:
        notification.status = NotificationStatus.FAILED
        notification.sent_at = None
        notification.error = send_result.error

    return NotificationDispatchResult(email_sent=False, error=send_result.error)


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
