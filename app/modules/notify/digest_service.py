from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import sanitize_log_message
from app.db.models.notify import Notification, NotificationChannel, NotificationStatus
from app.db.models.review import Change
from app.db.models.shared import User
from app.modules.common.family_labels import FamilyLabelAuthorityError, load_latest_family_labels
from app.modules.notify.notifier_factory import build_notifier
from app.modules.notify.service import _to_digest_item

NOTIFICATION_DISPATCH_BATCH_SIZE = 200


@dataclass(frozen=True)
class NotificationDispatchResult:
    processed_batches: int = 0
    sent_count: int = 0
    failed_count: int = 0
    sent_notification_count: int = 0
    failed_notification_count: int = 0


def dispatch_pending_notifications(db: Session, *, now: datetime | None = None) -> NotificationDispatchResult:
    current = now or datetime.now(timezone.utc)
    rows = db.execute(
        select(Notification, Change, User)
        .join(Change, Notification.change_id == Change.id)
        .join(User, Change.user_id == User.id)
        .where(
            Notification.channel == NotificationChannel.EMAIL,
            Notification.status == NotificationStatus.PENDING,
            Notification.notified_at.is_(None),
            Notification.deliver_after <= current,
        )
        .order_by(User.id.asc(), Change.detected_at.asc(), Notification.id.asc())
        .with_for_update(skip_locked=True, of=Notification)
        .limit(NOTIFICATION_DISPATCH_BATCH_SIZE)
    ).all()

    if not rows:
        return NotificationDispatchResult()

    grouped: dict[int, list[tuple[Notification, Change, User]]] = defaultdict(list)
    for row in rows:
        notification, _change, user = row
        grouped[user.id].append(row)

    processed_batches = 0
    sent_count = 0
    failed_count = 0
    sent_notification_count = 0
    failed_notification_count = 0
    notifier = build_notifier()

    for group_rows in grouped.values():
        processed_batches += 1
        notifications = [row[0] for row in group_rows]
        changes = [row[1] for row in group_rows]
        user = group_rows[0][2]

        to_email = _resolve_recipient(user)
        if to_email is None:
            _mark_notifications_failed(
                notifications,
                error="No notification recipient configured",
                current=current,
            )
            failed_count += 1
            failed_notification_count += len(notifications)
            continue

        family_ids = {
            family_id
            for change in changes
            for family_id in (
                _payload_family_id(change.before_semantic_json),
                _payload_family_id(change.after_semantic_json),
            )
            if isinstance(family_id, int)
        }
        latest_family_labels = load_latest_family_labels(db, user_id=user.id, family_ids=family_ids)
        try:
            items = [_to_digest_item(change, latest_family_labels=latest_family_labels) for change in changes]
        except FamilyLabelAuthorityError as exc:
            _mark_notifications_failed(
                notifications,
                error=sanitize_log_message(f"family_label_authority_error: {exc}"),
                current=current,
            )
            failed_count += 1
            failed_notification_count += len(notifications)
            continue
        send_result = notifier.send_changes_digest(
            to_email=to_email,
            review_label=_build_review_label(len(items)),
            user_id=user.id,
            items=items,
            timezone_name=user.timezone_name,
        )

        if not send_result.success:
            _mark_notifications_failed(
                notifications,
                error=sanitize_log_message(send_result.error or "unknown send failure"),
                current=current,
            )
            failed_count += 1
            failed_notification_count += len(notifications)
            continue

        for notification in notifications:
            notification.status = NotificationStatus.SENT
            notification.sent_at = current
            notification.notified_at = current
            notification.error = None

        sent_count += 1
        sent_notification_count += len(notifications)

    db.commit()
    return NotificationDispatchResult(
        processed_batches=processed_batches,
        sent_count=sent_count,
        failed_count=failed_count,
        sent_notification_count=sent_notification_count,
        failed_notification_count=failed_notification_count,
    )


def process_due_digests(db: Session, *, now: datetime | None = None) -> int:
    return dispatch_pending_notifications(db, now=now).processed_batches


def _build_review_label(review_count: int) -> str:
    return f"{review_count} new review" if review_count == 1 else f"{review_count} new reviews"


def _mark_notifications_failed(
    notifications: list[Notification],
    *,
    error: str,
    current: datetime,
) -> None:
    for notification in notifications:
        notification.status = NotificationStatus.FAILED
        notification.notified_at = current
        notification.error = error


def _resolve_recipient(user: User) -> str | None:
    settings = get_settings()
    for candidate in (user.notify_email, user.email, settings.default_notify_email):
        if candidate is None:
            continue
        stripped = candidate.strip()
        if stripped:
            return stripped
    return None


def _payload_family_id(payload: object) -> int | None:
    if not isinstance(payload, dict):
        return None
    family_id = payload.get("family_id")
    return family_id if isinstance(family_id, int) else None


__all__ = [
    "NotificationDispatchResult",
    "dispatch_pending_notifications",
    "process_due_digests",
]
