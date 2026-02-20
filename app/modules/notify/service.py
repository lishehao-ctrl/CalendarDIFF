from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

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

    pending_notifications: list[Notification] = []
    for change in changes:
        notification = Notification(
            change_id=change.id,
            channel=NotificationChannel.EMAIL,
            status=NotificationStatus.PENDING,
            sent_at=None,
            error=None,
        )
        db.add(notification)
        pending_notifications.append(notification)
    db.flush()

    settings = get_settings()
    to_email = settings.default_notify_email or (source.user.email if source.user else None)
    if not to_email:
        for notification in pending_notifications:
            notification.status = NotificationStatus.FAILED
            notification.error = "No notification recipient configured"
        return NotificationDispatchResult(email_sent=False, error="No notification recipient configured")

    notifier_impl = notifier or SMTPEmailNotifier()
    digest_items = [_to_digest_item(change) for change in changes]
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

    return ChangeDigestItem(
        event_uid=change.event_uid,
        change_type=change.change_type.value,
        course_label=course_label,
        title=title,
        before_start_at_utc=_read_timestamp(before_json.get("start_at_utc")),
        after_start_at_utc=_read_timestamp(after_json.get("start_at_utc")),
        delta_seconds=change.delta_seconds,
        detected_at=change.detected_at,
    )


def _read_timestamp(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
