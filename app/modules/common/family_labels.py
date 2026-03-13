from __future__ import annotations

from collections.abc import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.shared import CourseWorkItemLabelFamily


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
    snapshot_family_name: str | None,
    latest_family_labels: Mapping[int, str] | None = None,
) -> str | None:
    if isinstance(family_id, int) and latest_family_labels is not None:
        latest = latest_family_labels.get(family_id)
        if isinstance(latest, str) and latest.strip():
            return latest.strip()
    if isinstance(snapshot_family_name, str) and snapshot_family_name.strip():
        return snapshot_family_name.strip()
    return None


def semantic_family_equivalent(
    *,
    before_family_id: int | None,
    before_family_name: str | None,
    after_family_id: int | None,
    after_family_name: str | None,
) -> bool:
    if isinstance(before_family_id, int) or isinstance(after_family_id, int):
        return before_family_id == after_family_id
    before_name = before_family_name.strip().lower() if isinstance(before_family_name, str) and before_family_name.strip() else None
    after_name = after_family_name.strip().lower() if isinstance(after_family_name, str) and after_family_name.strip() else None
    return before_name == after_name


__all__ = [
    "load_latest_family_labels",
    "resolve_family_label",
    "semantic_family_equivalent",
]
