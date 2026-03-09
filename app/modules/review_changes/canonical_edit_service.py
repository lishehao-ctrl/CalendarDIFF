from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.review_changes.canonical_edit_apply_txn import execute_canonical_edit_apply_txn
from app.modules.review_changes.canonical_edit_errors import (
    CanonicalEditNotFoundError,
    CanonicalEditValidationError,
)
from app.modules.review_changes.canonical_edit_preview_flow import build_canonical_edit_preview


def preview_canonical_edit(
    db: Session,
    *,
    user_id: int,
    change_id: int | None,
    event_uid: str | None,
    due_at: str,
    title: str | None,
    course_label: str | None,
    reason: str | None,
) -> dict:
    return build_canonical_edit_preview(
        db=db,
        user_id=user_id,
        change_id=change_id,
        event_uid=event_uid,
        due_at=due_at,
        title=title,
        course_label=course_label,
        reason=reason,
    )


def apply_canonical_edit(
    db: Session,
    *,
    user_id: int,
    change_id: int | None,
    event_uid: str | None,
    due_at: str,
    title: str | None,
    course_label: str | None,
    reason: str | None,
) -> dict:
    return execute_canonical_edit_apply_txn(
        db=db,
        user_id=user_id,
        change_id=change_id,
        event_uid=event_uid,
        due_at=due_at,
        title=title,
        course_label=course_label,
        reason=reason,
    )


__all__ = [
    "CanonicalEditNotFoundError",
    "CanonicalEditValidationError",
    "apply_canonical_edit",
    "preview_canonical_edit",
]
