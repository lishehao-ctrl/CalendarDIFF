from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Change, Input, InputType, User
from app.modules.review_changes.manual_correction_errors import (
    ManualCorrectionNotFoundError,
    ManualCorrectionValidationError,
)


def load_user_or_raise(db: Session, *, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise ManualCorrectionNotFoundError("user not found")
    return user


def ensure_canonical_input_for_user(*, db: Session, user_id: int) -> Input:
    identity_key = f"canonical:user:{user_id}"
    input_row = db.scalar(
        select(Input).where(
            Input.user_id == user_id,
            Input.type == InputType.ICS,
            Input.identity_key == identity_key,
        )
    )
    if input_row is not None:
        return input_row
    input_row = Input(
        user_id=user_id,
        type=InputType.ICS,
        identity_key=identity_key,
        is_active=True,
    )
    db.add(input_row)
    db.flush()
    return input_row


def resolve_target_event_uid(
    db: Session,
    *,
    user_id: int,
    change_id: int | None,
    event_uid: str | None,
) -> str:
    normalized_event_uid = event_uid.strip() if isinstance(event_uid, str) else ""
    if event_uid is not None and not normalized_event_uid:
        raise ManualCorrectionValidationError("target.event_uid must not be blank")
    if change_id is None and not normalized_event_uid:
        raise ManualCorrectionValidationError("target.change_id or target.event_uid is required")

    change_event_uid: str | None = None
    if change_id is not None:
        row = db.scalar(
            select(Change)
            .join(Input, Input.id == Change.input_id)
            .where(Change.id == change_id, Input.user_id == user_id)
            .limit(1)
        )
        if row is None:
            raise ManualCorrectionNotFoundError("target change not found")
        change_event_uid = row.event_uid

    if change_event_uid is not None and normalized_event_uid and change_event_uid != normalized_event_uid:
        raise ManualCorrectionValidationError("target.change_id and target.event_uid must reference the same event_uid")

    resolved = normalized_event_uid or change_event_uid
    if not isinstance(resolved, str) or not resolved:
        raise ManualCorrectionValidationError("unable to resolve target event_uid")
    return resolved


__all__ = [
    "ensure_canonical_input_for_user",
    "load_user_or_raise",
    "resolve_target_event_uid",
]
