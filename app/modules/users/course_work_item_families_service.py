from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import SourceEventObservation
from app.db.models.shared import CourseWorkItemLabelFamily, User
from app.modules.common.course_identity import (
    course_display_name,
    normalize_course_identity,
    normalize_label_token,
    normalized_course_identity_key,
    parse_course_display,
)


class CourseWorkItemFamilyValidationError(RuntimeError):
    pass


class CourseWorkItemFamilyNotFoundError(RuntimeError):
    pass


def normalize_course_key(value: str | None) -> str:
    parsed = parse_course_display(value)
    return normalized_course_identity_key(
        course_dept=parsed["course_dept"] if isinstance(parsed["course_dept"], str) else None,
        course_number=parsed["course_number"] if isinstance(parsed["course_number"], int) else None,
        course_suffix=parsed["course_suffix"] if isinstance(parsed["course_suffix"], str) else None,
        course_quarter=parsed["course_quarter"] if isinstance(parsed["course_quarter"], str) else None,
        course_year2=parsed["course_year2"] if isinstance(parsed["course_year2"], int) else None,
    )


def normalize_raw_types(values: Iterable[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values or []:
        if not isinstance(value, str):
            continue
        normalized = normalize_label_token(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(value.strip()[:128])
    return out


def list_course_work_item_families(
    db: Session,
    *,
    user_id: int,
    course_key: str | None = None,
    course_dept: str | None = None,
    course_number: int | None = None,
    course_suffix: str | None = None,
    course_quarter: str | None = None,
    course_year2: int | None = None,
) -> list[CourseWorkItemLabelFamily]:
    identity = _coalesce_course_identity(
        course_key=course_key,
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
    )
    stmt = select(CourseWorkItemLabelFamily).where(CourseWorkItemLabelFamily.user_id == user_id)
    normalized_identity = normalized_course_identity_key(**identity)
    if normalized_identity:
        stmt = stmt.where(CourseWorkItemLabelFamily.normalized_course_identity == normalized_identity)
    stmt = stmt.order_by(
        CourseWorkItemLabelFamily.course_dept.asc(),
        CourseWorkItemLabelFamily.course_number.asc(),
        CourseWorkItemLabelFamily.course_suffix.asc(),
        CourseWorkItemLabelFamily.course_quarter.asc(),
        CourseWorkItemLabelFamily.course_year2.asc(),
        CourseWorkItemLabelFamily.canonical_label.asc(),
        CourseWorkItemLabelFamily.id.asc(),
    )
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
    course_key: str | None = None,
    course_dept: str | None = None,
    course_number: int | None = None,
    course_suffix: str | None = None,
    course_quarter: str | None = None,
    course_year2: int | None = None,
    canonical_label: str,
    raw_types: list[str],
    commit: bool = True,
) -> CourseWorkItemLabelFamily:
    from app.modules.users.course_raw_types_service import replace_family_raw_types

    identity = _require_course_identity(
        **_coalesce_course_identity(
            course_key=course_key,
            course_dept=course_dept,
            course_number=course_number,
            course_suffix=course_suffix,
            course_quarter=course_quarter,
            course_year2=course_year2,
        )
    )
    normalized_canonical_label = normalize_label_token(canonical_label)
    normalized_raw_types = normalize_raw_types(raw_types)
    if not normalized_canonical_label:
        raise CourseWorkItemFamilyValidationError("canonical_label must not be blank")
    _validate_family_uniqueness(
        db,
        user_id=user_id,
        normalized_course_identity=str(identity["normalized_course_identity"]),
        normalized_canonical_label=normalized_canonical_label,
        normalized_raw_types=[normalize_label_token(value) for value in normalized_raw_types],
    )
    row = CourseWorkItemLabelFamily(
        user_id=user_id,
        course_dept=str(identity["course_dept"]),
        course_number=int(identity["course_number"]),
        course_suffix=identity["course_suffix"] if isinstance(identity["course_suffix"], str) else None,
        course_quarter=identity["course_quarter"] if isinstance(identity["course_quarter"], str) else None,
        course_year2=identity["course_year2"] if isinstance(identity["course_year2"], int) else None,
        normalized_course_identity=str(identity["normalized_course_identity"]),
        canonical_label=canonical_label.strip()[:128],
        normalized_canonical_label=normalized_canonical_label,
    )
    db.add(row)
    db.flush()
    replace_family_raw_types(db, family=row, raw_types=normalized_raw_types, commit=False)
    if commit:
        db.commit()
        db.refresh(row)
    return row


def update_course_work_item_family(
    db: Session,
    *,
    family: CourseWorkItemLabelFamily,
    course_key: str | None = None,
    course_dept: str | None = None,
    course_number: int | None = None,
    course_suffix: str | None = None,
    course_quarter: str | None = None,
    course_year2: int | None = None,
    canonical_label: str,
    raw_types: list[str],
    commit: bool = True,
) -> CourseWorkItemLabelFamily:
    from app.modules.users.course_raw_types_service import replace_family_raw_types

    identity = _require_course_identity(
        **_coalesce_course_identity(
            course_key=course_key,
            course_dept=course_dept,
            course_number=course_number,
            course_suffix=course_suffix,
            course_quarter=course_quarter,
            course_year2=course_year2,
        )
    )
    normalized_canonical_label = normalize_label_token(canonical_label)
    normalized_raw_types = normalize_raw_types(raw_types)
    if not normalized_canonical_label:
        raise CourseWorkItemFamilyValidationError("canonical_label must not be blank")
    _validate_family_uniqueness(
        db,
        user_id=family.user_id,
        normalized_course_identity=str(identity["normalized_course_identity"]),
        normalized_canonical_label=normalized_canonical_label,
        normalized_raw_types=[normalize_label_token(value) for value in normalized_raw_types],
        exclude_family_id=family.id,
    )

    family.course_dept = str(identity["course_dept"])
    family.course_number = int(identity["course_number"])
    family.course_suffix = identity["course_suffix"] if isinstance(identity["course_suffix"], str) else None
    family.course_quarter = identity["course_quarter"] if isinstance(identity["course_quarter"], str) else None
    family.course_year2 = identity["course_year2"] if isinstance(identity["course_year2"], int) else None
    family.normalized_course_identity = str(identity["normalized_course_identity"])
    family.canonical_label = canonical_label.strip()[:128]
    family.normalized_canonical_label = normalized_canonical_label
    replace_family_raw_types(db, family=family, raw_types=normalized_raw_types, commit=False)
    if commit:
        db.commit()
        db.refresh(family)
    return family


def add_raw_type_to_course_work_item_family(
    db: Session,
    *,
    family: CourseWorkItemLabelFamily,
    raw_type: str,
    commit: bool = True,
) -> CourseWorkItemLabelFamily:
    from app.modules.users.course_raw_types_service import create_course_raw_type

    normalized_raw_type = normalize_label_token(raw_type)
    if not normalized_raw_type:
        raise CourseWorkItemFamilyValidationError("raw_type must not be blank")
    _validate_family_uniqueness(
        db,
        user_id=family.user_id,
        normalized_course_identity=family.normalized_course_identity,
        normalized_canonical_label=family.normalized_canonical_label,
        normalized_raw_types=[normalized_raw_type],
        exclude_family_id=family.id,
    )
    create_course_raw_type(db, family=family, raw_type=raw_type, commit=False)
    if commit:
        db.commit()
        db.refresh(family)
    return family


def resolve_course_work_item_family(
    db: Session,
    *,
    user_id: int,
    course_key: str | None = None,
    course_dept: str | None = None,
    course_number: int | None = None,
    course_suffix: str | None = None,
    course_quarter: str | None = None,
    course_year2: int | None = None,
    raw_label: str | None,
) -> dict[str, object]:
    from app.modules.users.course_raw_types_service import find_course_raw_type

    identity = _coalesce_course_identity(
        course_key=course_key,
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
    )
    normalized_identity = normalized_course_identity_key(**identity)
    normalized_label = normalize_label_token(raw_label)
    if not normalized_identity or not normalized_label:
        return {"status": "unresolved", "family_id": None, "canonical_label": None, "matched_alias": None, "raw_type_id": None}
    raw_type = find_course_raw_type(db, user_id=user_id, raw_type=normalized_label, **identity)
    if raw_type is not None and raw_type.family is not None:
        family = raw_type.family
        return {
            "status": "resolved",
            "family_id": family.id,
            "canonical_label": family.canonical_label,
            "matched_alias": raw_type.raw_type,
            "raw_type_id": raw_type.id,
        }
    for family in list_course_work_item_families(db, user_id=user_id, **identity):
        if family.normalized_canonical_label == normalized_label:
            return {
                "status": "resolved",
                "family_id": family.id,
                "canonical_label": family.canonical_label,
                "matched_alias": family.canonical_label,
                "raw_type_id": None,
            }
    return {"status": "unresolved", "family_id": None, "canonical_label": None, "matched_alias": None, "raw_type_id": None}


def list_known_course_identities(db: Session, *, user_id: int) -> list[dict[str, object]]:
    family_rows = list_course_work_item_families(db, user_id=user_id)
    items: dict[str, dict[str, object]] = {}
    for row in family_rows:
        payload = _safe_course_identity_payload(
            course_dept=row.course_dept,
            course_number=row.course_number,
            course_suffix=row.course_suffix,
            course_quarter=row.course_quarter,
            course_year2=row.course_year2,
        )
        if payload is not None:
            items[row.normalized_course_identity] = payload
    observation_rows = db.scalars(
        select(SourceEventObservation.event_payload).where(SourceEventObservation.user_id == user_id)
    ).all()
    for payload in observation_rows:
        if not isinstance(payload, dict):
            continue
        semantic_event = payload.get("semantic_event") if isinstance(payload.get("semantic_event"), dict) else {}
        identity = _safe_course_identity_payload(
            course_dept=semantic_event.get("course_dept") if isinstance(semantic_event.get("course_dept"), str) else None,
            course_number=semantic_event.get("course_number") if isinstance(semantic_event.get("course_number"), int) else None,
            course_suffix=semantic_event.get("course_suffix") if isinstance(semantic_event.get("course_suffix"), str) else None,
            course_quarter=semantic_event.get("course_quarter") if isinstance(semantic_event.get("course_quarter"), str) else None,
            course_year2=semantic_event.get("course_year2") if isinstance(semantic_event.get("course_year2"), int) else None,
        )
        if identity is not None:
            items[str(identity["normalized_course_identity"])] = identity
    return sorted(items.values(), key=lambda item: str(item["course_display"]))


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
    normalized_course_identity: str,
    normalized_canonical_label: str,
    normalized_raw_types: list[str],
    exclude_family_id: int | None = None,
) -> None:
    rows = db.scalars(
        select(CourseWorkItemLabelFamily).where(
            CourseWorkItemLabelFamily.user_id == user_id,
            CourseWorkItemLabelFamily.normalized_course_identity == normalized_course_identity,
        )
    ).all()
    for row in rows:
        if exclude_family_id is not None and row.id == exclude_family_id:
            continue
        if row.normalized_canonical_label == normalized_canonical_label:
            raise CourseWorkItemFamilyValidationError("canonical label already exists for this course")
        if row.normalized_canonical_label in normalized_raw_types:
            raise CourseWorkItemFamilyValidationError("raw type cannot match another family label in this course")
        existing_raw_types = {
            normalize_label_token(item.raw_type)
            for item in (row.raw_types if isinstance(row.raw_types, list) else [])
            if isinstance(getattr(item, "raw_type", None), str)
        }
        if normalized_canonical_label in existing_raw_types:
            raise CourseWorkItemFamilyValidationError("canonical label conflicts with an existing raw type in this course")
        if existing_raw_types.intersection(normalized_raw_types):
            raise CourseWorkItemFamilyValidationError("raw type already exists in another family for this course")


def _require_course_identity(
    *,
    course_dept: str | None,
    course_number: int | None,
    course_suffix: str | None,
    course_quarter: str | None,
    course_year2: int | None,
) -> dict[str, object]:
    normalized = normalize_course_identity(
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
    )
    if not isinstance(normalized["course_dept"], str) or not isinstance(normalized["course_number"], int):
        raise CourseWorkItemFamilyValidationError("course identity must include course_dept and course_number")
    return {
        **normalized,
        "normalized_course_identity": normalized_course_identity_key(
            course_dept=normalized["course_dept"],
            course_number=normalized["course_number"],
            course_suffix=normalized["course_suffix"] if isinstance(normalized["course_suffix"], str) else None,
            course_quarter=normalized["course_quarter"] if isinstance(normalized["course_quarter"], str) else None,
            course_year2=normalized["course_year2"] if isinstance(normalized["course_year2"], int) else None,
        ),
    }


def _safe_course_identity_payload(
    *,
    course_dept: str | None,
    course_number: int | None,
    course_suffix: str | None,
    course_quarter: str | None,
    course_year2: int | None,
) -> dict[str, object] | None:
    try:
        identity = _require_course_identity(
            course_dept=course_dept,
            course_number=course_number,
            course_suffix=course_suffix,
            course_quarter=course_quarter,
            course_year2=course_year2,
        )
    except CourseWorkItemFamilyValidationError:
        return None
    identity["course_display"] = course_display_name(
        course_dept=identity["course_dept"],
        course_number=identity["course_number"],
        course_suffix=identity["course_suffix"] if isinstance(identity["course_suffix"], str) else None,
        course_quarter=identity["course_quarter"] if isinstance(identity["course_quarter"], str) else None,
        course_year2=identity["course_year2"] if isinstance(identity["course_year2"], int) else None,
    )
    return identity


def _coalesce_course_identity(
    *,
    course_key: str | None = None,
    course_dept: str | None = None,
    course_number: int | None = None,
    course_suffix: str | None = None,
    course_quarter: str | None = None,
    course_year2: int | None = None,
) -> dict[str, object]:
    if course_key and (course_dept is None or course_number is None):
        parsed = parse_course_display(course_key)
        return {
            "course_dept": parsed["course_dept"] if isinstance(parsed["course_dept"], str) else None,
            "course_number": parsed["course_number"] if isinstance(parsed["course_number"], int) else None,
            "course_suffix": parsed["course_suffix"] if isinstance(parsed["course_suffix"], str) else None,
            "course_quarter": parsed["course_quarter"] if isinstance(parsed["course_quarter"], str) else None,
            "course_year2": parsed["course_year2"] if isinstance(parsed["course_year2"], int) else None,
        }
    return {
        "course_dept": course_dept,
        "course_number": course_number,
        "course_suffix": course_suffix,
        "course_quarter": course_quarter,
        "course_year2": course_year2,
    }


__all__ = [
    "CourseWorkItemFamilyNotFoundError",
    "CourseWorkItemFamilyValidationError",
    "add_raw_type_to_course_work_item_family",
    "create_course_work_item_family",
    "get_course_work_item_family",
    "list_course_work_item_families",
    "list_known_course_identities",
    "mark_course_work_item_family_rebuild_complete",
    "mark_course_work_item_family_rebuild_failed",
    "mark_course_work_item_family_rebuild_running",
    "normalize_course_key",
    "normalize_label_token",
    "normalize_raw_types",
    "resolve_course_work_item_family",
    "update_course_work_item_family",
]
