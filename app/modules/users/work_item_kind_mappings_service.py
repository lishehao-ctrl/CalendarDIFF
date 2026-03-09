from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.shared import User, UserWorkItemKindMapping

DEFAULT_WORK_ITEM_KIND_MAPPINGS = [
    {"name": "Homework", "aliases": ["hw", "homework"]},
    {"name": "Programming Assignment", "aliases": ["pa", "programming assignment"]},
    {"name": "Problem Set", "aliases": ["pset", "problem set"]},
    {"name": "Quiz", "aliases": ["quiz"]},
    {"name": "Exam", "aliases": ["exam", "midterm", "final"]},
    {"name": "Project", "aliases": ["project"]},
    {"name": "Lab", "aliases": ["lab"]},
    {"name": "Paper", "aliases": ["paper"]},
]


class WorkItemKindMappingValidationError(RuntimeError):
    pass


class WorkItemKindMappingNotFoundError(RuntimeError):
    pass


def normalize_work_item_kind_token(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    raw = raw.replace("-", " ").replace("_", " ")
    return " ".join(raw.split())[:128]


def normalize_aliases(values: Iterable[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values or []:
        if not isinstance(value, str):
            continue
        normalized = normalize_work_item_kind_token(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def ensure_default_work_item_kind_mappings(db: Session, *, user_id: int, commit: bool = True) -> list[UserWorkItemKindMapping]:
    existing = list_user_work_item_kind_mappings(db, user_id=user_id)
    if existing:
        return existing
    created: list[UserWorkItemKindMapping] = []
    now = datetime.now(timezone.utc)
    for item in DEFAULT_WORK_ITEM_KIND_MAPPINGS:
        row = UserWorkItemKindMapping(
            user_id=user_id,
            name=str(item["name"]),
            normalized_name=normalize_work_item_kind_token(str(item["name"])),
            aliases_json=normalize_aliases(item.get("aliases")),
        )
        db.add(row)
        created.append(row)
    user = db.get(User, user_id)
    if user is not None:
        user.work_item_mappings_state = "idle"
        user.work_item_mappings_last_rebuilt_at = now
        user.work_item_mappings_last_error = None
    if commit:
        db.commit()
        for row in created:
            db.refresh(row)
    else:
        db.flush()
    return created


def list_user_work_item_kind_mappings(db: Session, *, user_id: int) -> list[UserWorkItemKindMapping]:
    return list(
        db.scalars(
            select(UserWorkItemKindMapping)
            .where(UserWorkItemKindMapping.user_id == user_id)
            .order_by(UserWorkItemKindMapping.name.asc(), UserWorkItemKindMapping.id.asc())
        ).all()
    )


def get_user_work_item_kind_mapping(db: Session, *, user_id: int, mapping_id: int) -> UserWorkItemKindMapping | None:
    return db.scalar(
        select(UserWorkItemKindMapping)
        .where(UserWorkItemKindMapping.id == mapping_id, UserWorkItemKindMapping.user_id == user_id)
        .limit(1)
    )


def resolve_work_item_kind_mapping(db: Session, *, user_id: int, raw_kind_label: str | None) -> dict[str, object]:
    ensure_default_work_item_kind_mappings(db, user_id=user_id, commit=False)
    normalized = normalize_work_item_kind_token(raw_kind_label)
    if not normalized:
        return {"status": "unresolved", "mapping_id": None, "name": None, "matched_alias": None}
    for row in list_user_work_item_kind_mappings(db, user_id=user_id):
        if row.normalized_name == normalized:
            return {"status": "resolved", "mapping_id": row.id, "name": row.name, "matched_alias": row.name}
        aliases = row.aliases_json if isinstance(row.aliases_json, list) else []
        for alias in aliases:
            if isinstance(alias, str) and normalize_work_item_kind_token(alias) == normalized:
                return {"status": "resolved", "mapping_id": row.id, "name": row.name, "matched_alias": alias}
    return {"status": "unresolved", "mapping_id": None, "name": None, "matched_alias": None}


def create_user_work_item_kind_mapping(
    db: Session,
    *,
    user_id: int,
    name: str,
    aliases: list[str],
) -> UserWorkItemKindMapping:
    ensure_default_work_item_kind_mappings(db, user_id=user_id, commit=False)
    normalized_name = normalize_work_item_kind_token(name)
    if not normalized_name:
        raise WorkItemKindMappingValidationError("name must not be blank")
    normalized_aliases = normalize_aliases(aliases)
    _validate_mapping_uniqueness(db, user_id=user_id, normalized_name=normalized_name, normalized_aliases=normalized_aliases)
    row = UserWorkItemKindMapping(
        user_id=user_id,
        name=name.strip()[:128],
        normalized_name=normalized_name,
        aliases_json=normalized_aliases,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_user_work_item_kind_mapping(
    db: Session,
    *,
    mapping: UserWorkItemKindMapping,
    name: str,
    aliases: list[str],
) -> UserWorkItemKindMapping:
    normalized_name = normalize_work_item_kind_token(name)
    if not normalized_name:
        raise WorkItemKindMappingValidationError("name must not be blank")
    normalized_aliases = normalize_aliases(aliases)
    _validate_mapping_uniqueness(
        db,
        user_id=mapping.user_id,
        normalized_name=normalized_name,
        normalized_aliases=normalized_aliases,
        exclude_mapping_id=mapping.id,
    )
    mapping.name = name.strip()[:128]
    mapping.normalized_name = normalized_name
    mapping.aliases_json = normalized_aliases
    db.commit()
    db.refresh(mapping)
    return mapping


def delete_user_work_item_kind_mapping(db: Session, *, mapping: UserWorkItemKindMapping) -> None:
    db.delete(mapping)
    db.commit()


def mark_user_work_item_mapping_rebuild_running(db: Session, *, user: User) -> None:
    user.work_item_mappings_state = "running"
    user.work_item_mappings_last_error = None
    db.commit()
    db.refresh(user)


def mark_user_work_item_mapping_rebuild_complete(db: Session, *, user: User) -> None:
    user.work_item_mappings_state = "idle"
    user.work_item_mappings_last_rebuilt_at = datetime.now(timezone.utc)
    user.work_item_mappings_last_error = None
    db.commit()
    db.refresh(user)


def mark_user_work_item_mapping_rebuild_failed(db: Session, *, user: User, error: str) -> None:
    user.work_item_mappings_state = "failed"
    user.work_item_mappings_last_error = error[:1024]
    db.commit()
    db.refresh(user)


def _validate_mapping_uniqueness(
    db: Session,
    *,
    user_id: int,
    normalized_name: str,
    normalized_aliases: list[str],
    exclude_mapping_id: int | None = None,
) -> None:
    rows = list_user_work_item_kind_mappings(db, user_id=user_id)
    for row in rows:
        if exclude_mapping_id is not None and row.id == exclude_mapping_id:
            continue
        if row.normalized_name == normalized_name:
            raise WorkItemKindMappingValidationError("mapping name already exists")
        if row.normalized_name in normalized_aliases:
            raise WorkItemKindMappingValidationError("an alias cannot match another mapping name")
        aliases = row.aliases_json if isinstance(row.aliases_json, list) else []
        normalized_existing_aliases = {normalize_work_item_kind_token(alias) for alias in aliases if isinstance(alias, str)}
        if normalized_name in normalized_existing_aliases:
            raise WorkItemKindMappingValidationError("mapping name conflicts with an existing alias")
        if normalized_existing_aliases.intersection(normalized_aliases):
            raise WorkItemKindMappingValidationError("alias already exists in another mapping")


__all__ = [
    "DEFAULT_WORK_ITEM_KIND_MAPPINGS",
    "WorkItemKindMappingNotFoundError",
    "WorkItemKindMappingValidationError",
    "create_user_work_item_kind_mapping",
    "delete_user_work_item_kind_mapping",
    "ensure_default_work_item_kind_mappings",
    "get_user_work_item_kind_mapping",
    "list_user_work_item_kind_mappings",
    "mark_user_work_item_mapping_rebuild_complete",
    "mark_user_work_item_mapping_rebuild_failed",
    "mark_user_work_item_mapping_rebuild_running",
    "normalize_aliases",
    "normalize_work_item_kind_token",
    "resolve_work_item_kind_mapping",
    "update_user_work_item_kind_mapping",
]
