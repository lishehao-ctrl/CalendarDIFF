from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.shared import CourseWorkItemLabelFamily, CourseWorkItemRawType, User
from app.modules.families.rebuild_service import rebuild_user_work_item_state
from app.modules.families.family_service import (
    CourseWorkItemFamilyValidationError,
    create_course_work_item_family,
    update_course_work_item_family,
)
from app.modules.families.raw_type_service import (
    CourseRawTypeNotFoundError,
    CourseRawTypeValidationError,
    decide_raw_type_suggestion,
    get_raw_type_suggestion,
    move_course_raw_type_to_family,
)


class FamilyApplicationNotFoundError(RuntimeError):
    pass


class FamilyApplicationValidationError(RuntimeError):
    pass


def create_family_and_rebuild(
    db: Session,
    *,
    user: User,
    course_dept: str,
    course_number: int,
    course_suffix: str | None,
    course_quarter: str | None,
    course_year2: int | None,
    canonical_label: str,
    raw_types: list[str],
) -> CourseWorkItemLabelFamily:
    try:
        family = create_course_work_item_family(
            db,
            user_id=user.id,
            course_dept=course_dept,
            course_number=course_number,
            course_suffix=course_suffix,
            course_quarter=course_quarter,
            course_year2=course_year2,
            canonical_label=canonical_label,
            raw_types=raw_types,
        )
        db.refresh(user)
        rebuild_user_work_item_state(
            db,
            user=user,
            course_dept=course_dept,
            course_number=course_number,
            course_suffix=course_suffix,
            course_quarter=course_quarter,
            course_year2=course_year2,
        )
        return family
    except CourseWorkItemFamilyValidationError as exc:
        raise FamilyApplicationValidationError(str(exc)) from exc


def update_family_and_rebuild(
    db: Session,
    *,
    user: User,
    family: CourseWorkItemLabelFamily,
    canonical_label: str,
    raw_types: list[str],
) -> CourseWorkItemLabelFamily:
    try:
        updated = update_course_work_item_family(
            db,
            family=family,
            canonical_label=canonical_label,
            raw_types=raw_types,
        )
        db.refresh(user)
        rebuild_user_work_item_state(
            db,
            user=user,
            course_dept=family.course_dept,
            course_number=family.course_number,
            course_suffix=family.course_suffix,
            course_quarter=family.course_quarter,
            course_year2=family.course_year2,
        )
        return updated
    except CourseWorkItemFamilyValidationError as exc:
        raise FamilyApplicationValidationError(str(exc)) from exc


def relink_raw_type_and_rebuild(
    db: Session,
    *,
    user: User,
    raw_type: CourseWorkItemRawType,
    family: CourseWorkItemLabelFamily,
) -> tuple[CourseRawType, int]:
    try:
        previous_family_id = raw_type.family_id
        move_course_raw_type_to_family(db, raw_type=raw_type, family=family, commit=True)
        db.refresh(user)
        rebuild_user_work_item_state(
            db,
            user=user,
            course_dept=family.course_dept,
            course_number=family.course_number,
            course_suffix=family.course_suffix,
            course_quarter=family.course_quarter,
            course_year2=family.course_year2,
        )
        return raw_type, previous_family_id
    except CourseRawTypeValidationError as exc:
        raise FamilyApplicationValidationError(str(exc)) from exc


def decide_raw_type_suggestion_and_rebuild(
    db: Session,
    *,
    user: User,
    suggestion_id: int,
    decision: str,
    note: str | None,
) -> dict:
    row = get_raw_type_suggestion(db, user_id=user.id, suggestion_id=suggestion_id)
    if row is None:
        raise FamilyApplicationNotFoundError("raw type suggestion not found")
    try:
        updated = decide_raw_type_suggestion(db, user_id=user.id, suggestion=row, decision=decision, note=note)
    except (CourseRawTypeValidationError, CourseRawTypeNotFoundError) as exc:
        raise FamilyApplicationValidationError(str(exc)) from exc
    if decision.strip().lower() == "approve":
        family = updated.source_raw_type.family
        owner = family.user if family is not None else None
        if owner is not None:
            rebuild_user_work_item_state(
                db,
                user=owner,
                course_dept=family.course_dept,
                course_number=family.course_number,
                course_suffix=family.course_suffix,
                course_quarter=family.course_quarter,
                course_year2=family.course_year2,
            )
    db.commit()
    db.refresh(updated)
    return {
        "id": updated.id,
        "status": updated.status.value if hasattr(updated.status, "value") else str(updated.status),
        "review_note": updated.review_note,
        "reviewed_at": updated.reviewed_at,
    }


__all__ = [
    "FamilyApplicationNotFoundError",
    "FamilyApplicationValidationError",
    "create_family_and_rebuild",
    "decide_raw_type_suggestion_and_rebuild",
    "relink_raw_type_and_rebuild",
    "update_family_and_rebuild",
]
