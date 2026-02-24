from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import sanitize_log_message
from app.db.models import (
    Change,
    DigestSendLog,
    Input,
    Notification,
    NotificationChannel,
    NotificationStatus,
    User,
    UserNotificationPrefs,
)
from app.modules.notify.email import SMTPEmailNotifier
from app.modules.notify.service import _to_digest_item


def compute_due_slots(
    *,
    now_utc: datetime,
    timezone_name: str,
    digest_times: list[str],
    sent_slots: set[str],
) -> tuple[date, list[str]]:
    tz = _resolve_timezone(timezone_name)
    local_now = now_utc.astimezone(tz)
    local_date = local_now.date()

    due: list[str] = []
    for value in sorted(set(digest_times)):
        parsed = _parse_hhmm(value)
        if parsed is None:
            continue
        slot_dt = datetime.combine(local_date, parsed, tz)
        slot_key = f"{local_date.isoformat()}|{value}"
        if local_now >= slot_dt and slot_key not in sent_slots:
            due.append(value)
    return local_date, due


def process_due_digests(db: Session, *, now: datetime | None = None) -> int:
    current = now or datetime.now(timezone.utc)
    prefs_rows = db.scalars(select(UserNotificationPrefs).where(UserNotificationPrefs.digest_enabled.is_(True))).all()

    processed_slots = 0
    for prefs in prefs_rows:
        user = db.get(User, prefs.user_id)
        if user is None:
            continue

        sent_rows = db.scalars(
            select(DigestSendLog).where(
                DigestSendLog.user_id == user.id,
            )
        ).all()
        sent_keys = {f"{row.scheduled_local_date.isoformat()}|{row.scheduled_local_time}" for row in sent_rows}
        local_date, due_times = compute_due_slots(
            now_utc=current,
            timezone_name=prefs.timezone,
            digest_times=_as_str_list(prefs.digest_times),
            sent_slots=sent_keys,
        )
        for slot_time in due_times:
            send_digest_for_slot(
                db,
                user=user,
                scheduled_local_date=local_date,
                scheduled_local_time=slot_time,
                now=current,
            )
            processed_slots += 1

    return processed_slots


def send_digest_for_slot(
    db: Session,
    *,
    user: User,
    scheduled_local_date: date,
    scheduled_local_time: str,
    now: datetime | None = None,
) -> None:
    current = now or datetime.now(timezone.utc)

    existing = db.scalar(
        select(DigestSendLog.id).where(
            DigestSendLog.user_id == user.id,
            DigestSendLog.scheduled_local_date == scheduled_local_date,
            DigestSendLog.scheduled_local_time == scheduled_local_time,
        )
    )
    if existing is not None:
        return

    rows = db.execute(
        select(Notification, Change, Input)
        .join(Change, Notification.change_id == Change.id)
        .join(Input, Change.input_id == Input.id)
        .where(
            Notification.channel == NotificationChannel.EMAIL,
            Notification.status == NotificationStatus.PENDING,
            Notification.enqueue_reason == "digest_queue",
            Notification.notified_at.is_(None),
            Input.user_id == user.id,
        )
        .order_by(Change.detected_at.asc(), Notification.id.asc())
    ).all()

    if not rows:
        _insert_digest_log(
            db,
            user_id=user.id,
            scheduled_local_date=scheduled_local_date,
            scheduled_local_time=scheduled_local_time,
            status="skipped_empty",
            item_count=0,
            error=None,
            sent_at=current,
        )
        return

    to_email = _resolve_recipient(user)
    if to_email is None:
        _insert_digest_log(
            db,
            user_id=user.id,
            scheduled_local_date=scheduled_local_date,
            scheduled_local_time=scheduled_local_time,
            status="failed",
            item_count=0,
            error="No digest recipient configured",
            sent_at=current,
        )
        return

    notifications = [row[0] for row in rows]
    changes = [row[1] for row in rows]
    digest_items = [_to_digest_item(change) for change in changes]

    send_result = SMTPEmailNotifier().send_changes_digest(
        to_email,
        f"User {user.id} Digest",
        user.id,
        digest_items,
    )

    if not send_result.success:
        _insert_digest_log(
            db,
            user_id=user.id,
            scheduled_local_date=scheduled_local_date,
            scheduled_local_time=scheduled_local_time,
            status="failed",
            item_count=0,
            error=sanitize_log_message(send_result.error or "unknown send failure"),
            sent_at=current,
        )
        return

    for notification in notifications:
        notification.status = NotificationStatus.SENT
        notification.sent_at = current
        notification.notified_at = current
        notification.error = None

    _insert_digest_log(
        db,
        user_id=user.id,
        scheduled_local_date=scheduled_local_date,
        scheduled_local_time=scheduled_local_time,
        status="sent",
        item_count=len(notifications),
        error=None,
        sent_at=current,
    )


def _insert_digest_log(
    db: Session,
    *,
    user_id: int,
    scheduled_local_date: date,
    scheduled_local_time: str,
    status: str,
    item_count: int,
    error: str | None,
    sent_at: datetime,
) -> None:
    row = DigestSendLog(
        user_id=user_id,
        scheduled_local_date=scheduled_local_date,
        scheduled_local_time=scheduled_local_time,
        status=status,
        item_count=item_count,
        error=error,
        sent_at=sent_at,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _parse_hhmm(value: str) -> time | None:
    parts = value.split(":")
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return time(hour=hour, minute=minute)


def _resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:  # pragma: no cover - platform-specific tzdata behavior
        return ZoneInfo("UTC")


def _resolve_recipient(user: User) -> str | None:
    settings = get_settings()
    for candidate in (user.notify_email, user.email, settings.default_notify_email):
        if candidate is None:
            continue
        stripped = candidate.strip()
        if stripped:
            return stripped
    return None
