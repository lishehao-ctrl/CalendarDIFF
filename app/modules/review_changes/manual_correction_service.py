from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.review_changes.manual_correction_apply_txn import execute_manual_correction_apply_txn
from app.modules.review_changes.manual_correction_errors import (
    ManualCorrectionNotFoundError,
    ManualCorrectionValidationError,
)
from app.modules.review_changes.manual_correction_preview_flow import build_manual_correction_preview


def preview_manual_correction(
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
    return build_manual_correction_preview(
        db=db,
        user_id=user_id,
        change_id=change_id,
        event_uid=event_uid,
        due_at=due_at,
        title=title,
        course_label=course_label,
        reason=reason,
    )


def apply_manual_correction(
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
    return execute_manual_correction_apply_txn(
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
    "ManualCorrectionNotFoundError",
    "ManualCorrectionValidationError",
    "apply_manual_correction",
    "preview_manual_correction",
]
