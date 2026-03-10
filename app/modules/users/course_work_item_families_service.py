from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import SourceEventObservation
from app.db.models.shared import CourseWorkItemLabelFamily, User


class CourseWorkItemFamilyValidationError(RuntimeError):
    pass


class CourseWorkItemFamilyNotFoundError(RuntimeError):
    pass


def normalize_label_token(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    raw = raw.replace("-", " ").replace("_", " ")
    return " ".join(raw.split())[:128]


def normalize_course_key(value: str | None) -> str:
    return normalize_label_token(value)


def normalize_aliases(values: Iterable[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values or []:
        if not isinstance(value, str):
            continue
        normalized = normalize_label_token(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def list_course_work_item_families(
    db: Session,
    *,
    user_id: int,
    course_key: str | None = None,
) -> list[CourseWorkItemLabelFamily]:
    stmt = select(CourseWorkItemLabelFamily).where(CourseWorkItemLabelFamily.user_id == user_id)
    normalized_course_key = normalize_course_key(course_key)
    if normalized_course_key:
        stmt = stmt.where(CourseWorkItemLabelFamily.normalized_course_key == normalized_course_key)
    stmt = stmt.order_by(CourseWorkItemLabelFamily.course_key.asc(), CourseWorkItemLabelFamily.canonical_label.asc(), CourseWorkItemLabelFamily.id.asc())
    return list(db.scalars(stmt).all())


def get_course_work_item_family(db: Session, *, user_id: int, family_id: int) -> CourseWorkItemLabelFamily | None:
    return db.scalar(
        select(CourseWorkItemLabelFamily)
        .where(CourseWorkItemLabelFamily.id == family_id, CourseWorkItemLabelFamily.user_id == user_id)
        .limit(1)
    )


def create_course_work_item_family(
    db: Session,
    *,
    user_id: int,
    course_key: str,
    canonical_label: str,
    aliases: list[str],
) -> CourseWorkItemLabelFamily:
    normalized_course_key = normalize_course_key(course_key)
    normalized_canonical_label = normalize_label_token(canonical_label)
    if not normalized_course_key:
        raise CourseWorkItemFamilyValidationError("course_key must not be blank")
    if not normalized_canonical_label:
        raise CourseWorkItemFamilyValidationError("canonical_label must not be blank")
    normalized_aliases = normalize_aliases(aliases)
    _validate_family_uniqueness(
        db,
        user_id=user_id,
        normalized_course_key=normalized_course_key,
        normalized_canonical_label=normalized_canonical_label,
        normalized_aliases=normalized_aliases,
    )
    row = CourseWorkItemLabelFamily(
        user_id=user_id,
        course_key=course_key.strip()[:128],
        normalized_course_key=normalized_course_key,
        canonical_label=canonical_label.strip()[:128],
        normalized_canonical_label=normalized_canonical_label,
        aliases_json=normalized_aliases,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_course_work_item_family(
    db: Session,
    *,
    family: CourseWorkItemLabelFamily,
    course_key: str,
    canonical_label: str,
    aliases: list[str],
) -> CourseWorkItemLabelFamily:
    normalized_course_key = normalize_course_key(course_key)
    normalized_canonical_label = normalize_label_token(canonical_label)
    if not normalized_course_key:
        raise CourseWorkItemFamilyValidationError("course_key must not be blank")
    if not normalized_canonical_label:
        raise CourseWorkItemFamilyValidationError("canonical_label must not be blank")
    normalized_aliases = normalize_aliases(aliases)
    _validate_family_uniqueness(
        db,
        user_id=family.user_id,
        normalized_course_key=normalized_course_key,
        normalized_canonical_label=normalized_canonical_label,
        normalized_aliases=normalized_aliases,
        exclude_family_id=family.id,
    )
    family.course_key = course_key.strip()[:128]
    family.normalized_course_key = normalized_course_key
    family.canonical_label = canonical_label.strip()[:128]
    family.normalized_canonical_label = normalized_canonical_label
    family.aliases_json = normalized_aliases
    db.commit()
    db.refresh(family)
    return family


def delete_course_work_item_family(db: Session, *, family: CourseWorkItemLabelFamily) -> None:
    db.delete(family)
    db.commit()


def add_alias_to_course_work_item_family(
    db: Session,
    *,
    family: CourseWorkItemLabelFamily,
    alias: str,
) -> CourseWorkItemLabelFamily:
    normalized_alias = normalize_label_token(alias)
    if not normalized_alias:
        raise CourseWorkItemFamilyValidationError("alias must not be blank")
    current_aliases = family.aliases_json if isinstance(family.aliases_json, list) else []
    normalized_aliases = normalize_aliases([*current_aliases, normalized_alias])
    _validate_family_uniqueness(
        db,
        user_id=family.user_id,
        normalized_course_key=family.normalized_course_key,
        normalized_canonical_label=family.normalized_canonical_label,
        normalized_aliases=normalized_aliases,
        exclude_family_id=family.id,
    )
    family.aliases_json = normalized_aliases
    db.commit()
    db.refresh(family)
    return family


def remove_alias_from_course_work_item_family(
    db: Session,
    *,
    family: CourseWorkItemLabelFamily,
    alias: str,
) -> CourseWorkItemLabelFamily:
    normalized_alias = normalize_label_token(alias)
    aliases = family.aliases_json if isinstance(family.aliases_json, list) else []
    family.aliases_json = [value for value in aliases if normalize_label_token(value) != normalized_alias]
    db.commit()
    db.refresh(family)
    return family


def resolve_course_work_item_family(
    db: Session,
    *,
    user_id: int,
    course_key: str | None,
    raw_label: str | None,
) -> dict[str, object]:
    normalized_course_key = normalize_course_key(course_key)
    normalized_label = normalize_label_token(raw_label)
    if not normalized_course_key or not normalized_label:
        return {"status": "unresolved", "family_id": None, "canonical_label": None, "matched_alias": None}
    for family in list_course_work_item_families(db, user_id=user_id, course_key=normalized_course_key):
        if family.normalized_canonical_label == normalized_label:
            return {"status": "resolved", "family_id": family.id, "canonical_label": family.canonical_label, "matched_alias": family.canonical_label}
        aliases = family.aliases_json if isinstance(family.aliases_json, list) else []
        for alias in aliases:
            if normalize_label_token(alias) == normalized_label:
                return {"status": "resolved", "family_id": family.id, "canonical_label": family.canonical_label, "matched_alias": alias}
    return {"status": "unresolved", "family_id": None, "canonical_label": None, "matched_alias": None}


def list_known_course_keys(db: Session, *, user_id: int) -> list[str]:
    family_rows = list_course_work_item_families(db, user_id=user_id)
    family_keys = {row.course_key for row in family_rows if isinstance(row.course_key, str) and row.course_key.strip()}
    observation_rows = db.scalars(
        select(SourceEventObservation.event_payload).where(SourceEventObservation.user_id == user_id)
    ).all()
    for payload in observation_rows:
        if not isinstance(payload, dict):
            continue
        course_label = payload.get("course_label")
        if isinstance(course_label, str) and course_label.strip() and course_label.strip().lower() != "unknown":
            family_keys.add(course_label.strip()[:128])
    return sorted(family_keys)


def mark_course_work_item_family_rebuild_running(db: Session, *, user: User) -> None:
    user.work_item_mappings_state = "running"
    user.work_item_mappings_last_error = None
    db.commit()
    db.refresh(user)


def mark_course_work_item_family_rebuild_complete(db: Session, *, user: User) -> None:
    user.work_item_mappings_state = "idle"
    user.work_item_mappings_last_rebuilt_at = datetime.now(timezone.utc)
    user.work_item_mappings_last_error = None
    db.commit()
    db.refresh(user)


def mark_course_work_item_family_rebuild_failed(db: Session, *, user: User, error: str) -> None:
    user.work_item_mappings_state = "failed"
    user.work_item_mappings_last_error = error[:1024]
    db.commit()
    db.refresh(user)


def _validate_family_uniqueness(
    db: Session,
    *,
    user_id: int,
    normalized_course_key: str,
    normalized_canonical_label: str,
    normalized_aliases: list[str],
    exclude_family_id: int | None = None,
) -> None:
    rows = list_course_work_item_families(db, user_id=user_id, course_key=normalized_course_key)
    for row in rows:
        if exclude_family_id is not None and row.id == exclude_family_id:
            continue
        if row.normalized_canonical_label == normalized_canonical_label:
            raise CourseWorkItemFamilyValidationError("canonical label already exists for this course")
        if row.normalized_canonical_label in normalized_aliases:
            raise CourseWorkItemFamilyValidationError("an alias cannot match another family label in this course")
        aliases = row.aliases_json if isinstance(row.aliases_json, list) else []
        normalized_existing_aliases = {normalize_label_token(alias) for alias in aliases if isinstance(alias, str)}
        if normalized_canonical_label in normalized_existing_aliases:
            raise CourseWorkItemFamilyValidationError("canonical label conflicts with an existing alias in this course")
        if normalized_existing_aliases.intersection(normalized_aliases):
            raise CourseWorkItemFamilyValidationError("alias already exists in another family for this course")


__all__ = [
    "CourseWorkItemFamilyNotFoundError",
    "CourseWorkItemFamilyValidationError",
    "add_alias_to_course_work_item_family",
    "create_course_work_item_family",
    "delete_course_work_item_family",
    "get_course_work_item_family",
    "list_course_work_item_families",
    "list_known_course_keys",
    "mark_course_work_item_family_rebuild_complete",
    "mark_course_work_item_family_rebuild_failed",
    "mark_course_work_item_family_rebuild_running",
    "normalize_aliases",
    "normalize_course_key",
    "normalize_label_token",
    "remove_alias_from_course_work_item_family",
    "resolve_course_work_item_family",
    "update_course_work_item_family",
]
