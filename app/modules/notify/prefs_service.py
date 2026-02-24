from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import UserNotificationPrefs
from app.modules.notify.prefs_schemas import normalize_digest_times

DEFAULT_DIGEST_TIMES = ["09:00"]


def get_or_create_notification_prefs(db: Session, *, user_id: int) -> UserNotificationPrefs:
    row = db.get(UserNotificationPrefs, user_id)
    if row is not None:
        if not isinstance(row.digest_times, list) or not row.digest_times:
            row.digest_times = DEFAULT_DIGEST_TIMES.copy()
            db.commit()
            db.refresh(row)
        return row

    row = UserNotificationPrefs(
        user_id=user_id,
        digest_enabled=True,
        timezone="America/Los_Angeles",
        digest_times=DEFAULT_DIGEST_TIMES.copy(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_notification_prefs(
    db: Session,
    *,
    row: UserNotificationPrefs,
    digest_enabled: bool | None = None,
    timezone: str | None = None,
    digest_times: list[str] | None = None,
) -> UserNotificationPrefs:
    if digest_enabled is not None:
        row.digest_enabled = digest_enabled
    if timezone is not None:
        row.timezone = timezone
    if digest_times is not None:
        normalized = normalize_digest_times(digest_times)
        if len(normalized) < 1 or len(normalized) > 6:
            raise ValueError("digest_times must contain between 1 and 6 entries")
        row.digest_times = normalized

    db.commit()
    db.refresh(row)
    return row
