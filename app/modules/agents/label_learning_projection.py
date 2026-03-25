from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.changes.label_learning_service import (
    LabelLearningNotFoundError,
    LabelLearningValidationError,
    preview_label_learning,
)
from app.modules.families.family_service import get_course_work_item_family


class LabelLearningProjectionValidationError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def build_label_learning_projection(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    family_id: int,
) -> dict:
    try:
        preview = preview_label_learning(db, user_id=user_id, change_id=change_id)
    except LabelLearningNotFoundError as exc:
        raise LabelLearningProjectionValidationError(
            code="agents.context.label_learning_not_found",
            message=str(exc),
        ) from exc
    except LabelLearningValidationError as exc:
        raise LabelLearningProjectionValidationError(
            code="agents.proposals.label_learning.invalid",
            message=str(exc),
        ) from exc

    family = get_course_work_item_family(db, user_id=user_id, family_id=family_id)
    if family is None:
        raise LabelLearningProjectionValidationError(
            code="agents.context.family_not_found",
            message="Family not found",
        )

    preview_families = preview.get("families") if isinstance(preview.get("families"), list) else []
    target_family_snapshot = next(
        (
            row
            for row in preview_families
            if isinstance(row, dict) and int(row.get("id") or 0) == int(family_id)
        ),
        None,
    )
    if target_family_snapshot is None:
        raise LabelLearningProjectionValidationError(
            code="agents.proposals.label_learning.cross_course_not_allowed",
            message="Observed label can only map into an existing family in the same course",
        )

    raw_label = str(preview.get("raw_label") or "").strip()
    if not raw_label:
        raise LabelLearningProjectionValidationError(
            code="agents.proposals.label_learning.raw_label_missing",
            message="Label learning requires an observed label",
        )

    return {
        "change": {
            "change_id": int(preview["change_id"]),
            "course_display": preview.get("course_display"),
            "raw_label": raw_label,
            "status": preview.get("status"),
            "resolved_family_id": preview.get("resolved_family_id"),
            "resolved_canonical_label": preview.get("resolved_canonical_label"),
        },
        "target_family": {
            "family_id": int(target_family_snapshot["id"]),
            "canonical_label": target_family_snapshot.get("canonical_label"),
            "course_display": target_family_snapshot.get("course_display"),
            "raw_types": list(target_family_snapshot.get("raw_types") or []),
        },
        "impact": {
            "approved_change_count": 1,
            "pending_change_count": 1,
            "risk_level": "low",
            "risk_reason_code": "agents.proposals.label_learning_commit.low_risk",
        },
    }


__all__ = [
    "LabelLearningProjectionValidationError",
    "build_label_learning_projection",
]
