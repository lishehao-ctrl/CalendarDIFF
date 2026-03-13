from __future__ import annotations

from collections.abc import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.shared import CourseWorkItemLabelFamily


class FamilyLabelAuthorityError(RuntimeError):
    pass


def load_latest_family_labels(
    db: Session,
    *,
    user_id: int,
    family_ids: Iterable[int | None],
) -> dict[int, str]:
    normalized_family_ids = sorted({int(family_id) for family_id in family_ids if isinstance(family_id, int) and family_id > 0})
    if not normalized_family_ids:
        return {}

    rows = db.execute(
        select(CourseWorkItemLabelFamily.id, CourseWorkItemLabelFamily.canonical_label).where(
            CourseWorkItemLabelFamily.user_id == user_id,
            CourseWorkItemLabelFamily.id.in_(normalized_family_ids),
        )
    ).all()
    return {
        int(family_id): canonical_label.strip()
        for family_id, canonical_label in rows
        if isinstance(family_id, int) and isinstance(canonical_label, str) and canonical_label.strip()
    }


def resolve_family_label(
    *,
    family_id: int | None,
    latest_family_labels: Mapping[int, str] | None = None,
) -> str | None:
    if isinstance(family_id, int) and latest_family_labels is not None:
        latest = latest_family_labels.get(family_id)
        if isinstance(latest, str) and latest.strip():
            return latest.strip()
    return None


def require_latest_family_label(
    *,
    family_id: int | None,
    latest_family_labels: Mapping[int, str] | None,
    context: str,
) -> str:
    if not isinstance(family_id, int) or family_id <= 0:
        raise FamilyLabelAuthorityError(f"{context}: missing family_id authority")
    if latest_family_labels is None:
        raise FamilyLabelAuthorityError(f"{context}: latest family label map missing for family_id={family_id}")
    resolved = resolve_family_label(
        family_id=family_id,
        latest_family_labels=latest_family_labels,
    )
    if not isinstance(resolved, str) or not resolved.strip():
        raise FamilyLabelAuthorityError(
            f"{context}: unresolved latest canonical_label authority for family_id={family_id}"
        )
    return resolved.strip()


def semantic_family_equivalent(
    *,
    before_family_id: int | None,
    after_family_id: int | None,
) -> bool:
    return before_family_id == after_family_id


__all__ = [
    "FamilyLabelAuthorityError",
    "load_latest_family_labels",
    "require_latest_family_label",
    "resolve_family_label",
    "semantic_family_equivalent",
]
